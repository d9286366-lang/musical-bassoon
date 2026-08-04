import os
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                          login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'retro-messenger-secret-key-2010'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'messenger.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите в аккаунт'


# ==================== МОДЕЛИ ====================

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    avatar_emoji = db.Column(db.String(8), default='😺')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User', backref='posts')


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User')
    post = db.relationship('Post', backref=db.backref('comments', order_by='Comment.timestamp'))


class Reaction(db.Model):
    """value = 1 -> лайк (кот улыбается), value = -1 -> дизлайк (кот грустный)"""
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    value = db.Column(db.Integer, nullable=False)

    __table_args__ = (db.UniqueConstraint('post_id', 'user_id', name='uniq_reaction'),)

    post = db.relationship('Post', backref='reactions')


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(256))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    resolved = db.Column(db.Boolean, default=False)

    post = db.relationship('Post', backref='reports')
    reporter = db.relationship('User')


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])


class Follow(db.Model):
    """follower_id подписан на followed_id.
    Если оба подписаны друг на друга - они друзья."""
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('follower_id', 'followed_id', name='uniq_follow'),)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ==================== ВСПОМОГАТЕЛЬНОЕ ====================

EMOJIS = ['😺', '😸', '😹', '😻', '😽', '😾', '😿', '🙀',
          '☺', '😊', '😄', '😆', '😉', '😢', '😭', '😡',
          '😎', '😳', '😜', '❤', '👍', '👎', '🎉', '⭐',
          '🔥', '💤', '🤔', '💔', '✌', '🎵', '☕', '🌹']


def reaction_counts(post):
    likes = sum(1 for r in post.reactions if r.value == 1)
    dislikes = sum(1 for r in post.reactions if r.value == -1)
    return likes, dislikes


def user_reaction(post, user):
    if not user.is_authenticated:
        return None
    r = Reaction.query.filter_by(post_id=post.id, user_id=user.id).first()
    return r.value if r else None


def is_following(follower_id, followed_id):
    if follower_id == followed_id:
        return False
    return Follow.query.filter_by(follower_id=follower_id, followed_id=followed_id).first() is not None


def are_friends(user_id_a, user_id_b):
    if user_id_a == user_id_b:
        return False
    return is_following(user_id_a, user_id_b) and is_following(user_id_b, user_id_a)


app.jinja_env.globals.update(
    reaction_counts=reaction_counts,
    user_reaction=user_reaction,
    is_following=is_following,
    are_friends=are_friends,
)


@app.context_processor
def inject_globals():
    return dict(EMOJIS=EMOJIS)


# ==================== АУТЕНТИФИКАЦИЯ ====================

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        if not username or not password:
            flash('Заполните логин и пароль!', 'error')
        elif len(username) < 3:
            flash('Логин слишком короткий (минимум 3 символа)', 'error')
        elif len(password) < 4:
            flash('Пароль слишком короткий (минимум 4 символа)', 'error')
        elif password != password2:
            flash('Пароли не совпадают!', 'error')
        elif User.query.filter_by(username=username).first():
            flash('Такой логин уже занят :(', 'error')
        else:
            user = User(username=username)
            user.set_password(password)
            if User.query.count() == 0:
                user.is_admin = True  # первый зарегистрированный = администратор
            db.session.add(user)
            db.session.commit()
            flash('Регистрация прошла успешно! Теперь войдите в аккаунт.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('feed'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Добро пожаловать, ' + user.username + '!', 'success')
            return redirect(url_for('feed'))
        flash('Неверный логин или пароль!', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ==================== ЛЕНТА / ПОСТЫ ====================

@app.route('/', methods=['GET', 'POST'])
@login_required
def feed():
    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        if text:
            post = Post(user_id=current_user.id, text=text)
            db.session.add(post)
            db.session.commit()
            flash('Пост опубликован!', 'success')
        return redirect(url_for('feed'))

    tab = request.args.get('tab', 'all')

    if tab == 'friends':
        following_ids = {f.followed_id for f in Follow.query.filter_by(follower_id=current_user.id).all()}
        follower_ids = {f.follower_id for f in Follow.query.filter_by(followed_id=current_user.id).all()}
        friend_ids = following_ids & follower_ids
        posts = (Post.query.filter(Post.user_id.in_(friend_ids)).order_by(Post.timestamp.desc()).all()
                 if friend_ids else [])
    elif tab == 'subs':
        following_ids = [f.followed_id for f in Follow.query.filter_by(follower_id=current_user.id).all()]
        posts = (Post.query.filter(Post.user_id.in_(following_ids)).order_by(Post.timestamp.desc()).all()
                 if following_ids else [])
    else:
        tab = 'all'
        posts = Post.query.order_by(Post.timestamp.desc()).all()

    return render_template('feed.html', posts=posts, tab=tab)


@app.route('/post/<int:post_id>')
@login_required
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template('post.html', post=post)


@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    text = request.form.get('text', '').strip()
    if text:
        c = Comment(post_id=post.id, user_id=current_user.id, text=text)
        db.session.add(c)
        db.session.commit()
    return redirect(url_for('post_detail', post_id=post.id))


@app.route('/post/<int:post_id>/react/<int:value>')
@login_required
def react(post_id, value):
    if value not in (1, -1):
        abort(400)
    post = Post.query.get_or_404(post_id)
    r = Reaction.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if r:
        if r.value == value:
            db.session.delete(r)  # повторный клик по той же реакции - отмена
        else:
            r.value = value
    else:
        r = Reaction(post_id=post.id, user_id=current_user.id, value=value)
        db.session.add(r)
    db.session.commit()
    return redirect(request.referrer or url_for('feed'))


@app.route('/post/<int:post_id>/report', methods=['POST'])
@login_required
def report_post(post_id):
    post = Post.query.get_or_404(post_id)
    reason = request.form.get('reason', 'Не указана')
    existing = Report.query.filter_by(post_id=post.id, reporter_id=current_user.id, resolved=False).first()
    if existing:
        flash('Вы уже жаловались на этот пост, жалоба на рассмотрении.', 'error')
    else:
        rep = Report(post_id=post.id, reporter_id=current_user.id, reason=reason)
        db.session.add(rep)
        db.session.commit()
        flash('Жалоба отправлена администратору. Спасибо!', 'success')
    return redirect(request.referrer or url_for('feed'))


@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if not (current_user.is_admin or current_user.id == post.user_id):
        abort(403)
    Comment.query.filter_by(post_id=post.id).delete()
    Reaction.query.filter_by(post_id=post.id).delete()
    Report.query.filter_by(post_id=post.id).delete()
    db.session.delete(post)
    db.session.commit()
    flash('Пост удалён.', 'success')
    return redirect(request.referrer or url_for('feed'))


# ==================== ПОДПИСКИ И ДРУЗЬЯ ====================

@app.route('/user/<int:user_id>/follow', methods=['POST'])
@login_required
def follow_user(user_id):
    if user_id == current_user.id:
        abort(400)
    target = User.query.get_or_404(user_id)
    if not is_following(current_user.id, target.id):
        db.session.add(Follow(follower_id=current_user.id, followed_id=target.id))
        db.session.commit()
        if is_following(target.id, current_user.id):
            flash('Теперь вы с ' + target.username + ' друзья! 🤝', 'success')
        else:
            flash('Вы подписались на ' + target.username + '.', 'success')
    return redirect(request.referrer or url_for('feed'))


@app.route('/user/<int:user_id>/unfollow', methods=['POST'])
@login_required
def unfollow_user(user_id):
    target = User.query.get_or_404(user_id)
    f = Follow.query.filter_by(follower_id=current_user.id, followed_id=target.id).first()
    if f:
        db.session.delete(f)
        db.session.commit()
        flash('Вы отписались от ' + target.username + '.', 'success')
    return redirect(request.referrer or url_for('feed'))


# ==================== АДМИН-ПАНЕЛЬ ====================

@app.route('/admin')
@login_required
def admin_panel():
    if not current_user.is_admin:
        abort(403)
    reports = Report.query.filter_by(resolved=False).order_by(Report.timestamp.desc()).all()
    users = User.query.all()
    return render_template('admin.html', reports=reports, users=users)


@app.route('/admin/report/<int:report_id>/dismiss', methods=['POST'])
@login_required
def dismiss_report(report_id):
    if not current_user.is_admin:
        abort(403)
    rep = Report.query.get_or_404(report_id)
    rep.resolved = True
    db.session.commit()
    flash('Жалоба закрыта.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/user/<int:user_id>/toggle_admin', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        abort(403)
    user = User.query.get_or_404(user_id)
    if user.id != current_user.id:
        user.is_admin = not user.is_admin
        db.session.commit()
    return redirect(url_for('admin_panel'))


# ==================== ЛИЧНЫЕ СООБЩЕНИЯ ====================

@app.route('/messages')
@login_required
def messages_list():
    sent = Message.query.filter_by(sender_id=current_user.id).all()
    received = Message.query.filter_by(receiver_id=current_user.id).all()
    partner_ids = set(m.receiver_id for m in sent) | set(m.sender_id for m in received)
    partners = User.query.filter(User.id.in_(partner_ids)).all() if partner_ids else []
    all_users = User.query.filter(User.id != current_user.id).all()
    return render_template('messages.html', partners=partners, all_users=all_users)


@app.route('/messages/<int:user_id>', methods=['GET', 'POST'])
@login_required
def chat(user_id):
    partner = User.query.get_or_404(user_id)
    if partner.id == current_user.id:
        abort(400)
    if request.method == 'POST':
        text = request.form.get('text', '').strip()
        if text:
            msg = Message(sender_id=current_user.id, receiver_id=partner.id, text=text)
            db.session.add(msg)
            db.session.commit()
        return redirect(url_for('chat', user_id=partner.id))
    msgs = Message.query.filter(
        db.or_(
            db.and_(Message.sender_id == current_user.id, Message.receiver_id == partner.id),
            db.and_(Message.sender_id == partner.id, Message.receiver_id == current_user.id)
        )
    ).order_by(Message.timestamp.asc()).all()
    return render_template('chat.html', partner=partner, msgs=msgs)


# ==================== ОШИБКИ ====================

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, text='Доступ запрещён! Это только для администраторов.'), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, text='Страница не найдена.'), 404


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)
