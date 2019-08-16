from flask import render_template, redirect, url_for, request, \
                g, current_app, abort, jsonify, make_response
from flask_login import current_user
from . import main
from .forms import SearchForm
from ..models import *
from ..utils import *
from .. import cache
import json


def nextPost(post):
    """
    获取本篇文章的下一篇
    :param post: post
    :return: next post
    """
    next_post = Post.query.filter_by(draft=False).filter(Post.id>post.id).order_by(Post.id.asc()).first()
    if next_post:
        return next_post
    return None

def prevPost(post):
    """
    获取本篇文章的上一篇
    :param post: post
    :return: prev post
    """
    prev_post = Post.query.filter_by(draft=False).filter(Post.id<post.id).order_by(Post.id.desc()).first()
    if prev_post:
        return prev_post
    return None


def get_post_cache(key):
    """获取博客文章缓存"""
    data = cache.get(key)
    if data:
        return data
    else:
        items = key.split('$#$#')
        return set_post_cache(items[1])

def set_post_cache(pid):
    """设置博客文章缓存"""
    post = Post.query.filter_by(id=pid).first()
    tags = [tag for tag in post.tags.split(',')]
    next_post = nextPost(post)
    prev_post = prevPost(post)
    data = post.to_dict()
    data['tags'] = tags
    data['next_post'] = {
        'year': next_post.year,
        'month': next_post.month,
        'url': next_post.url_name,
        'title': next_post.title,
        'id': next_post.id
    } if next_post else None
    data['prev_post'] = {
        'year': prev_post.year,
        'month': prev_post.month,
        'url': prev_post.url_name,
        'title': prev_post.title,
        'id': prev_post.id
    } if prev_post else None
    cache_key = '$#$#'.join(map(str, ['post', pid]))
    cache.set(cache_key, data, timeout=60 * 60 * 24 * 30)
    return data


@main.before_request
def before_request():
    g.search_form = SearchForm()
    g.search_form2 = SearchForm()


@main.app_errorhandler(404)
def page_not_found(e):
    return render_template('error/404.html', title='404'), 404

@main.app_errorhandler(500)
def internal_server_error(e):
    db.session.rollback()
    db.session.commit()
    return render_template('error/500.html', title='500'), 500



@main.route('/')
@main.route('/index')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config['POSTS_PER_PAGE']
    pagination = Post.query.filter_by(draft=False).order_by(Post.id.desc()).paginate(page, per_page=per_page,error_out=False)
    posts = pagination.items
    return render_template('main/index.html', title='首页',
                           posts=posts, page=page,
                           pagination=pagination)

@main.route('/archives/<int:pid>')
def post(pid):
    cache_key = '$#$#'.join(map(str, ['post', pid]))
    post = get_post_cache(cache_key)

    page = request.args.get('page', 1, type=int)

    comment_data=get_comments(pid=post['id'],page_id=None,article_id=None,page=page)

    pagination=comment_data['pagination']
    comments=comment_data['comments']
    total=comment_data['total']
    max_page=comment_data['max_page']

    meta_tags = ','.join(post['tags'])
    return render_template('main/post.html', post=post, title=post['title'],page=page,
                   pagination=pagination, comments=comments,max_page=max_page,
                   counts=total, meta_tags=meta_tags)

@main.route('/page/<page_url>')
def page(page_url):
    p = request.args.get('page', 1, type=int)
    page_cls = Page.query.filter_by(url_name=page_url).first()

    comment_data=get_comments(page_id=page_cls.id,pid=None,article_id=None,page=p)

    pagination=comment_data['pagination']
    comments=comment_data['comments']
    total=comment_data['total']
    max_page=comment_data['max_page']

    return render_template('main/page.html', page_cls=page_cls,page=p, title=page_cls.title, pagination=pagination,max_page=max_page,
                           comments=comments, counts=total)

@main.route('/tag/<tag_name>/')
def tag(tag_name):
    tag = tag_name
    posts = Post.query.filter_by(draft=False).order_by(Post.id.desc()).all()
    return render_template('main/tag.html', tag=tag, posts=posts)

@main.route('/category/<category_name>/')
def category(category_name):
    category = Category.query.filter_by(category=category_name).first()
    posts = Post.query.filter_by(category=category, draft=False).order_by(Post.id.desc()).all()
    return render_template('main/category.html',
                           category=category,
                           posts=posts,
                           title='分类：' + category.category)

@main.route('/archives/')
def archives():
    count = Post.query.filter_by(draft=False).count()
    page = request.args.get('page', 1, type=int)
    pagination = Post.query.filter_by(draft=False).order_by(Post.id.desc()).paginate(
        page, per_page=current_app.config['ACHIVES_POSTS_PER_PAGE'],
        error_out=False)
    posts = pagination.items
    year = list(set([i.year for i in posts]))[::-1]
    data = {}
    year_post = []
    for y in year:
        for p in posts:
            if y == p.year:
                year_post.append(p)
                data[y] = year_post
        year_post = []

    return render_template('main/archives.html', title='归档', posts=posts,
                           year=year, data=data, count=count,
                           pagination=pagination)

@main.route('/search/', methods=['POST'])
def search():
    if g.search_form.validate_on_submit():
        query = g.search_form.search.data
        return redirect(url_for('main.search_result', keywords=query))

    elif g.search_form2.validate_on_submit():
        query = g.search_form2.search.data
        return redirect(url_for('main.search_result', keywords=query))

# /search-result?keywords=query
@main.route('/search-result')
def search_result():
    query = request.args.get('keywords')
    page = request.args.get('page', 1, type=int)
    pagination = Post.query.whooshee_search(query).order_by(Post.id.desc()).paginate(
        page, per_page=current_app.config['SEARCH_POSTS_PER_PAGE'],
        error_out=False
    )
    results = (post for post in pagination.items if post.draft is False)
    return render_template('main/results.html', results=results,
                           query=query, pagination=pagination,
                           title=query + '的搜索结果')

# 侧栏 love me 插件
@main.route('/loveme', methods=['POST','GET'])
def love_me():
    """
    :return: json
    """
    return jsonify('ok')
    data = request.get_json()
    if data.get('i_am_handsome', '') == 'yes':
        # 更新缓存
        global_cache = cache.get('global')
        if global_cache['loves'] is not None:
            global_cache['loves'] += 1
        else:
            global_cache['loves'] =1
        cache.set('global', global_cache)
        love_me_counts = LoveMe.query.all()[0]
        love_me_counts.loveMe += 1
        db.session.add(love_me_counts)
        db.session.commit()
        return jsonify(counts=love_me_counts.loveMe)
    return jsonify(you_are_sb='yes')


# 保存评论的函数
def save_comment(post, form):
    # 站点链接
    base_url = Admin.query.filter_by(id=1).first().site_url
    #是否管理员评论
    disabled=True if current_user.is_authenticated and current_user.id==1 else False

    nickname = form['nickname']
    email = form['email']
    website = form['website'] or None
    com = form['comment'].replace('<', '&lt;').replace('>', '&gt;')\
        .replace('"', '&quot;').replace('\'', '&apos;')
    replyTo = form.get('replyTo', '')
    if replyTo:
        replyName = Comment.query.get(replyTo).author
        comment = Comment(comment=com, author=nickname,email=email,
                          website=website, isReply=True, parent_id=replyTo)
        data = {'nickname': nickname, 'email': email, 'website': website,
                'comment': com, 'isReply': True, 'replyTo': replyTo}
    else:
        comment = Comment(comment=com, author=nickname, email=email, website=website)
        data = {'nickname': nickname, 'email': email, 'website': website, 'comment': com}

    post_url = ''
    if isinstance(post, Post):
        post_url=base_url + '/archives/' + str(post.id)
        comment.post = post
        cache.delete_memoized(get_comments,post.id,None,None)
    elif isinstance(post, Page):
        post_url = base_url + '/page/' + post.url_name
        comment.page = post
        cache.delete_memoized(get_comments,None,post.id,None)
    elif isinstance(post, Article):
        post_url = base_url + '/column/' + post.column.url_name + '/' + str(post.id)
        comment.article = post
        cache.delete_memoized(get_comments,None,None,post.id)
    comment.disabled=disabled
    db.session.add(comment)
    db.session.commit()
    return data

@main.route('/<type>/<id>/comment', methods=['POST'])
def comment(type,id):
    if type=='post':
        post=Post.query.filter_by(id=id).first()
    elif type=='page':
        post=Page.query.filter_by(id=id).first()
    elif type=='column':
        post=Article.query.filter_by(id=id).first()
    form = request.get_json()
    data = save_comment(post, form)
    if data.get('replyTo'):
        return jsonify(nickname=data['nickname'], email=data['email'],
                       website=data['website'], body=data['comment'],
                       isReply=data['isReply'], replyTo=data['replyTo'], post=post.title)
    return jsonify(nickname=data['nickname'], email=data['email'],
                   website=data['website'], body=data['comment'], post=post.title)

@main.route('/shuoshuo')
def shuoshuo():
    shuos = Shuoshuo.query.order_by(Shuoshuo.id.desc()).all()
    years = list(set([y.year for y in shuos]))[::-1]
    data = {}
    year_shuo = []
    for y in years:
        for s in shuos:
            if y == s.year:
                year_shuo.append(s)
                data[y] = year_shuo
        year_shuo = []
    return render_template('main/shuoshuo.html', title='说说', years=years, data=data)

# friend link page
@main.route('/friends')
def friends():
    friends = SiteLink.query.filter_by(isFriendLink=True).order_by(SiteLink.id.desc()).all()
    great_links = [link for link in friends if link.isGreatLink is True]
    bad_links = [link for link in friends if link.isGreatLink is False]

    return render_template('main/friends.html', title="朋友",
                           great_links=great_links, bad_links=bad_links)




