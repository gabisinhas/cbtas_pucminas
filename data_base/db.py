import logging
import os
import datetime
import uuid
from flask import session
from cloudant.client import Cloudant
from cloudant.adapters import Replay429Adapter
from cloudant.document import Document
from components.util.tools import synchronized

# ---------------------------------------------------- #
#                    Logging Setup                     #
# ---------------------------------------------------- #
logging.basicConfig(level=logging.INFO)
from components.util.tools import synchronized
from data_base import partitions

def setDatabase():
    global my_database
    db_name = os.getenv('DB_NAME')
    db_user = os.getenv('DB_USER')
    db_pass = os.getenv('DB_PWD')
    db_url = os.getenv('DB_URL')

    db = Cloudant.iam(db_user, db_pass, url=db_url, connect=True,
                      adapter=Replay429Adapter(retries=30, initialBackoff=0.03))
    my_database = db[db_name]

@synchronized
def next_id():
    """"This function will generate a new request id based on latest one saved on database"""
    try:
        # 1. Database connection setup
        setDatabase()

        # 2. Retrieve the document
        docs = db_get_all_by_partition(partitions.get_partitions()["settings"])

        # 3. Get the latest ID
        latest_id = docs[0]["latest_id"]

        # 4. Increment to the next one
        latest_id = latest_id + 1

        # 5. Generate the full ID
        parse_id = "SR" + str(latest_id).zfill(6)

        # 6. Update the latest ID
        doc = Document(my_database, docs[0]['_id'])
        doc.fetch()
        doc.field_set(doc, 'latest_id', latest_id)
        doc.save()
        print('doc')

        # 7. Return
        return parse_id
        print('parse_id')

    except Exception as e:
        logging.warning(msg="ID generation exception: " + str(e))
        raise


def db_get_all_by_partition(partition_key=None):
    """This function returns all documents from a partition """

    if partition_key:
        # 1. Defining database connection
        setDatabase()

        # 3. Query by partition
        result = my_database.partitioned_all_docs(partition_key, include_docs=True)

        # 4. Processing the result
        docs = []
        for doc in result['rows']:
            docs.append(doc['doc'])

        return docs

    return None


def db_create(doc, partition=None):

    if partition and doc:

        # 1. Prepare database connection
        setDatabase()

        # 2. Define Document ID based on partition and aleatory ID
        doc['_id'] = "{partition}:{id}".format(partition=partition,
                                               id=str(uuid.uuid4()))

        # 3. Create the document
        new_doc = my_database.create_document(doc)
        if new_doc:
            return {'status': True,
                    '_id': doc['_id']}

    return {'status': None,
            '_id': None}


def db_delete_by_id(doc_id):

    # 1. Connect to database
    setDatabase()

    # 2. Select the doc
    if doc_id in my_database:

        doc = my_database[doc_id]

        # 2.2 Delete document
        doc.delete()

        return True

    else:
        return False


def db_update(doc):
    doc_id = doc['_id']
    setDatabase()
    if doc_id in my_database:
        doc_to_update = my_database[doc_id]
        doc_to_update.update(doc)
        doc_to_update.save()
        return doc_to_update
    else:
        return False

def db_select_all():
    setDatabase()
    selector = {'_id': {'$gt': '0'}}
    result = my_database.get_query_result(selector)
    docs = []
    for doc in result:
        docs.append(doc)
    return docs


def db_search_selector(selector=None, fields=None, sort=None):
    """This function queries the database based in a selector filter """

    # 1. Defining database connection
    setDatabase()

    # 2. initializing variables
    doc = {}

    # 3. Validation selector and executing the query
    if selector is not None:

        if sort:
            result = my_database.get_query_result(selector=selector, fields=fields, sort=sort)
        else:
            result = my_database.get_query_result(selector=selector, fields=fields)

    # 4. Processing the result
    docs = []
    for doc in result:
        docs.append(doc)

    return docs


def db_search_selector_partitioned(selector=None, fields=None, sort=None, partition_key=None):
    """This function queries the database based in a selector filter """

    # 1. Defining database connection
    setDatabase()

    # 2. initializing variables
    doc = {}

    # 3. Validation selector and executing the query
    if selector is not None:

        if sort:
            result = my_database.get_partitioned_query_result(selector=selector, fields=fields, sort=sort, partition_key=partition_key)
        else:
            result = my_database.get_partitioned_query_result(selector=selector, fields=fields, partition_key=partition_key)

    # 4. Processing the result
    docs = []
    for doc in result:
        docs.append(doc)

    return docs


def db_select_by_id(doc_id):
    setDatabase()
    selector = {'_id': {'$eq': doc_id}}
    result = my_database.get_query_result(selector)
    for doc in result:
        return doc
    return None


def db_add_access_user(email):
    """"This function will add a new user"""

    try:
        # 1. Get the settings document
        settings = db_search_selector({
            "type": {
                "$eq": "settings"
            }
        }, [])

        users = settings[0]['access']['users']

        # 3. If the exist already
        if email in users and email:
            return 202
        else:
            # 4. Add the new user
            access = settings[0]['access']
            access['users'][email] = []

            # 5. Save the doc
            settings[0]['access'] = access
            db_update(settings[0])

            logging.info(msg="New user added: {0}".format(email))
            return 200
        return True

    except Exception as e:
        logging.warning(msg="Getting user exceptions: " + str(e))
        raise


def db_remove_access_user(email):
    """"This function will remove a user role"""
    try:
        # 1. Get the settings document
        settings = db_search_selector({
            "type": {
                "$eq": "settings"
            }
        }, [])

        users = settings[0]['access']['users']
        user_countries = settings[0]['access']['countries']

        # 2. If the email doesn't exist already
        if email in users and email:

            # 3. Remove the user from user list
            access = settings[0]['access']
            del access['users'][email]
            settings[0]['access'] = access

            # 4. Remove the user from country focal list
            for country in user_countries:
                # If the user is in some country
                if email in country['focal_point']:
                    # Remove the user from this country
                    country['focal_point'].remove(email)

            # Update the settings document to reflect the user removed from
            # user access list and user per country
            db_update(settings[0])

            # 5. Remove the user from country documents
            # Query the database looking for documents that
            # have the given user as reviewer
            data = db_search_selector({
                "reviewer": {
                    "$elemMatch": {
                        "$eq": email
                    }
                }
            }, [])

            # Iterate all documents found to remove the user
            for country_doc in data:
                # Remove the user from the country document
                country_doc['reviewer'].remove(email)
                # Update the document in the database
                db_update(country_doc)

            logging.info(msg="User removed: {0}".format(email))

        return True

    except Exception as e:
        logging.warning(msg="Getting user removing exceptions: " + str(e))
        raise


def db_add_access_user_role(user, role):
    """"This function will update a roles of a given user"""
    try:
        # 1. Get the settings document
        settings = db_search_selector({
            "type": {
                "$eq": "settings"
            }
        }, [])

        # 2. Roles
        roles = settings[0]['access']['users'][user]

        # 3. Update the user's roles
        access = settings[0]['access']
        roles.append(role)
        access['users'][user] = roles

        # 4. Save the doc
        settings[0]['access'] = access
        db_update(settings[0])

        logging.info(msg="User roles updated: {0}".format(user))

        return True

    except Exception as e:
        logging.warning(msg="Getting adding user role exceptions: " + str(e))
        raise


def db_remove_access_user_role(user, role):
    """"This function will update a roles of a given user"""

    try:
        # 1. Get the settings document
        settings = db_search_selector({
            "type": {
                "$eq": "settings"
            }
        }, [])

        # 2. Roles
        roles = settings[0]['access']['users'][user]

        # 4. Update the user's roles
        access = settings[0]['access']
        if role in roles:
            roles.remove(role)
        access['users'][user] = roles

        # 5. Save the doc
        settings[0]['access'] = access
        db_update(settings[0])

        # 6. Remove the user from country focal list
        data = db_search_selector({
                "reviewer": {
                    "$elemMatch": {
                        "$eq": user
                    }
                }
            }, [])
        for country_doc in data:
            # Remove the user from the country document
            country_doc['reviewer'].remove(user)
            # Update the document in the database
            db_update(country_doc)

        logging.info(msg="User roles updated: {0}".format(user))

        return True

    except Exception as e:
        logging.warning(msg="Getting removing user role exceptions: " + str(e))
        raise

def db_get_user_roles(email):
    """"This function will return user roles"""
    try:
        # 1. Get roles
        setDatabase()
        view_name = 'settings'
        design_doc = '_design/select_doc'

        config_doc = my_database.get_view_result(ddoc_id=design_doc, view_name=view_name, raw_result=True,
                                                 include_docs=True)
        users = config_doc['rows'][0]['doc']['access']['users']

        roles = []
        if email in users:
            roles = users[email]

        return roles

    except Exception as e:
        logging.warning(msg="Getting role exceptions: " + str(e))
        raise


def db_get_settings():
    """"This function will return user roles"""
    try:
        # 1. Get roles
        setDatabase()
        view_name = 'settings'
        design_doc = '_design/select_doc'

        config_doc = my_database.get_view_result(ddoc_id=design_doc, view_name=view_name, raw_result=True,
                                                 include_docs=True)
        return config_doc['rows'][0]['doc']

    except Exception as e:
        logging.warning(msg="Getting role exceptions: " + str(e))
        raise
