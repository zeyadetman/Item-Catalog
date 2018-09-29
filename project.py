from sqlalchemy import create_engine, asc
from sqlalchemy.orm import sessionmaker, scoped_session
from Catalog_db import Base, Category, Item, User
from flask import session as login_session
import random
import string
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    jsonify,
    url_for,
    flash
)

app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Category Items Application"

# Connect to Database and create database session
engine = create_engine('sqlite:///itemcategory.db')
Base.metadata.bind = engine

session = scoped_session(sessionmaker(bind=engine))


# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(
        string.ascii_uppercase + string.digits)
        for x in range(32)
    )
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login.html', STATE=state)


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(
            json.dumps('Invalid state parameter.'),
            401
        )
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print("Token's client ID does not match app's.")
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'),
            200
        )
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']
    # ADD PROVIDER TO LOGIN SESSION
    login_session['provider'] = 'google'

    # see if user exists, if it doesn't make a new one
    user_id = getUserID(data["email"])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius:'
    flash("you are now logged in as %s" % login_session['username'])
    print("done!")
    return output


# User Helper Functions


def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session[
        'email'], picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session['email']).one()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except Exception:
        return None


# DISCONNECT - Revoke a current user's token and reset their login_session


@app.route('/gdisconnect')
def gdisconnect():
    # Only disconnect a connected user.
    access_token = login_session.get('access_token')
    if access_token is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    if result['status'] == '200':
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        response = make_response(
            json.dumps('Failed to revoke token for given user.'),
            400
        )
        response.headers['Content-Type'] = 'application/json'
        return response


################################
#         (APIS JOSN)         #
################################

# JSON APIs to view All Catalogs Information
@app.route('/Api/Category/JSON')
def categoryJSON():
    catalogs = session.query(Category).all()
    return jsonify(Catalogs=[r.serialize for r in catalogs])


# JSON APIs to view items of specific Catalog Information
@app.route('/Api/Category/<int:category_id>/items/JSON')
def categoryItemsJSON(category_id):
    items = session.query(Item).filter_by(
        category_id=category_id).all()
    return jsonify(items=[i.serialize for i in items])


# JSON APIs to view specific item of specific Catalog Information
@app.route('/Api/Category/<int:category_id>/items/<int:item_id>/JSON')
def itemJSON(category_id, item_id):
    item = session.query(Item).filter_by(id=item_id).one()
    return jsonify(Item=item.serialize)


##############################################
#           (Code Funcationality CRUD)       #
##############################################

# Show all catalogs
@app.route('/')
@app.route('/Category/')
def showCategory():
    catalogs = session.query(Category).order_by(asc(Category.name))
    if 'username' not in login_session:
        return render_template('publicCategory.html', catalogs=catalogs)
    else:
        return render_template('categories.html', catalogs=catalogs)


# Create a new newCategory
@app.route('/Category/new/', methods=['GET', 'POST'])
def newCategory():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newCategory = Category(
            name=request.form['name'],
            user_id=login_session['user_id'],
            picture=request.form['picture']
        )
        session.add(newCategory)
        flash('New Catalog %s Successfully Created' % newCategory.name)
        session.commit()
        return redirect(url_for('showCategory'))
    else:
        return render_template('newCategory.html')


# Edit a Catalog
@app.route(
    '/Category/<int:category_id>/edit/',
    methods=['GET', 'POST']
)
def editCategory(category_id):
    editedCategory = session.query(
        Category).filter_by(id=category_id).one()
    if 'username' not in login_session:
        return redirect('/login')
    if editedCategory.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert(" \
               "'You are not authorized to edit this catalog." \
               " Please create your own catalog in order to edit.');}" \
               "</script><body onload='myFunction()'>"
    if request.method == 'POST':
        if request.form['name']:
            editedCategory.name = request.form['name']
        if request.form['picture']:
            editedCategory.picture = request.form['picture']
        session.add(editedCategory)
        flash('Restaurant Successfully Edited %s' % editedCategory.name)
        session.commit()
        return redirect(url_for('showCategory'))
    else:
        return render_template(
            'editCategory.html',
            catalog=editedCategory
        )


# Delete a Catalog
@app.route(
    '/Category/<int:category_id>/delete/',
    methods=['GET', 'POST']
)
def deleteCategory(category_id):
    catalogToDelete = session.query(
        Category).filter_by(id=category_id).one()
    if 'username' not in login_session:
        return redirect('/login')
    if catalogToDelete.user_id != login_session['user_id']:
        return "<script>function myFunction() {alert(" \
               "'You are not authorized to delete this catalog." \
               " Please create your own catalog in order to delete.');}" \
               "</script><body onload='myFunction()'>"
    if request.method == 'POST':
        session.delete(catalogToDelete)
        flash('%s Successfully Deleted' % catalogToDelete.name)
        session.commit()
        return redirect(url_for('showCategory', category_id=category_id))
    else:
        return render_template('deleteCategory.html', catalog=catalogToDelete)


# Show a Catalog Items
@app.route('/Category/<int:category_id>/items/')
def showItems(category_id):
    catalog = session.query(Category).filter_by(id=category_id).one()
    creator = session.query(User).filter_by(id=catalog.user_id).one()
    # return str(catalog.user.id)
    items = session.query(Item).filter_by(
        category_id=category_id).all()
    if 'username' not in login_session or (
        catalog.user.id != login_session['user_id']
    ):
        return render_template(
            'publicItems.html',
            items=items,
            catalog=catalog,
            creator=creator
        )
    else:
        return render_template(
            'items.html',
            items=items,
            catalog=catalog,
            creator=catalog
        )


# Show Details of Item
@app.route('/Category/<int:category_id>/items/<int:item_id>/Details')
def publicshowItem(category_id, item_id):
    item = session.query(Item).filter_by(id=item_id).one()
    catalog = session.query(Category).filter_by(id=category_id).one()
    if 'username' not in login_session or (
        catalog.user.id != login_session['user_id']
    ):
        return render_template(
            'publicshowItem.html',
            item=item,
            catalog=catalog,
            creator=catalog.user.name
        )
    else:
        return render_template(
            'showItem.html',
            item=item, catalog=catalog,
            creator=catalog.user.name
        )


# Create a new item
@app.route('/Category/<int:category_id>/items/new/', methods=['GET', 'POST'])
def newCategoryItem(category_id):
    if 'username' not in login_session:
        return redirect('/login')
    catalog = session.query(Category).filter_by(id=category_id).one()
    if login_session['user_id'] != catalog.user_id:
        return "<script>function myFunction() {alert(" \
               "'You are not authorized to add menu items to this catalog." \
               " Please create your own catalog in order to add items.');}" \
               "</script><body onload='myFunction()'>"
    if request.method == 'POST':
        item = Item(
            name=request.form['name'],
            description=request.form['description'],
            price=request.form['price'],
            picture=request.form['picture'],
            category_id=category_id
        )
        session.add(item)
        session.commit()
        flash('New Menu %s Item Successfully Created' % (item.name))
        return redirect(url_for('showItems', category_id=category_id))
    else:
        return render_template('newCategoryItem.html', category_id=category_id)


# Edit a catalog item
@app.route(
    '/Category/<int:category_id>/Items/<int:item_id>/edit',
    methods=['GET', 'POST']
)
def editCategoryItem(category_id, item_id):
    if 'username' not in login_session:
        return redirect('/login')
    editedItem = session.query(Item).filter_by(id=item_id).one()
    catalog = session.query(Category).filter_by(id=category_id).one()
    if login_session['user_id'] != catalog.user_id:
        return "<script>function myFunction() {alert(" \
               "'You are not authorized to edit item items to this catalog. "\
               "Please create your own catalog in order to edit items.');}" \
               "</script><body onload='myFunction()'>"
    if request.method == 'POST':
        editedItem1 = session.query(Item).filter_by(id=item_id).one()
        if request.form['name']:
            editedItem1.name = request.form['name']
        if request.form['description']:
            editedItem1.description = request.form['description']
        if request.form['price']:
            editedItem1.price = request.form['price']
        if request.form['picture']:
            editedItem1.pucture = request.form['picture']
        session.add(editedItem1)
        session.commit()
        flash('Menu Item Successfully Edited')
        return redirect(
            url_for(
                'showItems',
                category_id=editedItem1.category_id
            )
        )
    else:
        catalogs = session.query(Category).all()
        # return str(editedItem.id)
        return render_template(
            'editcategoryitem.html',
            catalogs=catalogs,
            category_id=category_id,
            item_id=item_id,
            item=editedItem
        )


# Delete a catalog item
@app.route(
    '/Category/<int:category_id>/Items/<int:item_id>/delete',
    methods=['GET', 'POST']
)
def deleteCategoryItem(category_id, item_id):
    if 'username' not in login_session:
        return redirect('/login')
    restaurant = session.query(Category).filter_by(id=category_id).one()
    itemToDelete = session.query(Item).filter_by(id=item_id).one()
    if login_session['user_id'] != restaurant.user_id:
        return "<script>function myFunction() {alert('You are not" \
               " authorized to delete catalog items to this catalog. Please" \
               " create your own catalog in order to delete items.');}" \
               "</script><body onload='myFunction()'>"
    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        flash('Menu Item Successfully Deleted')
        return redirect(url_for('showItems', category_id=category_id))
    else:
        return render_template(
            'deleteCategoryItem.html',
            item=itemToDelete,
            category_id=category_id
        )


# Disconnect based on provider
@app.route('/disconnect')
def disconnect():
    if 'provider' in login_session:
        if login_session['provider'] == 'google':
            gdisconnect(login_session)
            del login_session['gplus_id']
            del login_session['access_token']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        del login_session['user_id']
        del login_session['provider']
        flash("You have successfully been logged out.")
        return redirect(url_for('showCategory'))
    else:
        flash("You were not logged in")
        return redirect(url_for('showCategory'))


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='localhost', port=5000)
