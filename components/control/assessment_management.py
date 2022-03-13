import os

from flask import Blueprint, jsonify, request, session

from components.model import communication
from components.model.templates import template_notification, template_notification_requester
from data_base import partitions
from data_base.database_operations import db_search_selector, db_get_all_by_partition, db_select_by_id
from components.security.security_management import authentication
import components.model.assessment as assessment_model
import data_base.model as data_model
import components.util.bluepages as bluepages
import logging
import components.model.access as access
import data_base.database_operations as database


# 1. Define the blueprint that will hold routes for assessment_management (organizer)
assessment_management = Blueprint('assessment_management', __name__)


# 2. Define the route that will manage the assessment subject requests
@assessment_management.route('/assessment-management/assessment/', methods=['GET', 'POST', 'PUT', 'DELETE'])  # it is the decorator that will promote this function to API
def assessment():

    """This component manages the CBTA assessment"""

    logging.info(">>assessment: Starting<<")

    try:
        # 1. Add a Assessment Request
        if request.method == 'POST':

            # 1. Get Input data
            if request.json: # Validate if the request has content in the body as JSON

                new_assessment = request.json

                # Define the Support Owner
                support_contact = access.get_assessment_support(type_query=new_assessment['query_type'])

                new_assessment['support_contact'] = support_contact

                # Add assessment
                code_result, result = assessment_model.add_assessment(assessment=new_assessment)

                logging.info(">> assessment: POST <<")
                return jsonify({'_id': result["_id"], 'assessment_id': result["assessment_id"]}), code_result

        if request.method == 'PUT':

            # 1. Get Input data
            if request.json: # Validate if the request has content in the body as JSON
                # Get the assessment document from database
                updated_doc = request.json

                database.db_update(updated_doc)

                logging.info(">> assessment: PUT <<")
                return jsonify({}), 200
            else:
                # Missing data
                return jsonify({}), 204

        # 2. Get Assessment Request
        if request.method == 'GET':
            code, result = assessment_model.get_assessments()
            return jsonify(result), code

    except Exception as e:
        logging.error("** assessment: exception ** ")
        logging.exception(str(e))
        return jsonify({'status': 'Internal error'}), 500


@assessment_management.route('/assessment-management/user/', methods=['GET'])  # Get current logged user data
@assessment_management.route('/assessment-management/user/<serial_number>', methods=['GET'])  # Get custom user data
def assessment_user(serial_number=None):
    try:

        # Get current logged user data
        if request.method == 'GET' and serial_number is None:
            employee_data = bluepages.get_person_data_include_manager(email=session["email"])

            newco_user = False
            if session["employeetype"] != "IBM":
                newco_user = True
            employee_data[1]["newco_user"] = newco_user

            return jsonify(employee_data), 200

        # Get custom user data
        if request.method == 'GET' and serial_number is not None:
            employee_data = bluepages.get_person_data_include_manager(serial_number=serial_number)
            return jsonify(employee_data), 200

    except Exception as e:
        logging.error("** assessment_user: exception ** ")
        logging.exception(str(e))
        return jsonify({'status': 'Internal error'}), 500


@assessment_management.route('/assessment-management/assessment/user/', methods=['GET'])
def user_assessments():
    """Retrieve current user assessment requests"""

    logging.info(">>user_assessments: Starting<<")

    try:
        code, result = assessment_model.get_user_owned_assessment(ibm_user_serial=session["serial_number"])

        return jsonify(result), code

    except Exception as e:
        logging.error("** user_assessments: exception ** ")
        logging.exception(str(e))
        return jsonify({'status': 'Internal error'}), 500


@assessment_management.route('/assessment-management/assessment/admin/', methods=['GET'])
@authentication
def request_all_assessment_data():
    """See all the assessment on the DB"""

    try:
        logging.info(">> assessment_management_admin: Starting << ")
        # 1. Define database query to retrieve the overall assessment data
        code, result = assessment_model.get_assessments() # []
        newco_user = False
        if session["employeetype"] != "IBM":
            newco_user = True
        new_result = {
            'assessments': result,
            'newco_user': newco_user
        }
        # 2. Return the data
        logging.info(">> assessment_management_admin: finished << ")
        return jsonify(new_result), code
    except Exception as e:
        logging.error("** assessment_management_permission: exception ** ")
        logging.exception(str(e))
        resp = jsonify({'message': 'Internal error in the resource, please contact the administrator.'})
        return resp, 500


@assessment_management.route('/assessment-management/assessment/admin/<assessment_id>', methods=['GET'])
@authentication
def view_assessment(assessment_id=None):
    """See the assessment on the DB"""

    # Define database query to retrieve the overall assessment data
    try:
        logging.info(">> view_assessment_admin: Starting << ")

        if request.method == 'GET' and assessment_id is not None:
            assessment_id = "assessment:{key}".format(key=assessment_id)
            result = db_select_by_id(doc_id=assessment_id)
            newco_user = False
            if session["employeetype"] != "IBM":
                newco_user = True
            result["newco_user"] = newco_user
            return jsonify(result), 200

    except Exception as e:
        logging.error("** view_assessment_admin: exception ** ")
        logging.exception(str(e))
        return jsonify({'status': 'Internal error'}), 500


@assessment_management.route('/assessment-management/assessment/<id>/attachment', methods=['POST', 'PUT'])
@assessment_management.route('/assessment-management/assessment/<id>/attachment/<file_name>', methods=['GET'])
def assessment_management_attachments(id=None, file_name=None):
    logging.info(">>assessment_management_attachments: starting<<")

    try:

        from base64 import b64encode, b64decode

        if request.method == 'POST':
            logging.info(">>assessment_management_attachments: Add <<")

            # 1. Generate the list of files
            file_list = []
            for file in request.files.items():
                file_list.append(
                    {'file_name': file[1].filename,
                     'content_type': file[1].mimetype,
                     'data': b64encode(file[1].read())
                     })

            # 2. Parse the document ID
            doc_id = id.replace("_._", ":").format()

            # 3. Add attachment(s) to the document
            doc = database.add_attachment(doc_id=doc_id,
                                          file_list=file_list)

            # 4. Return the result
            if doc:
                return jsonify({}), 200

        if request.method == 'PUT':
            logging.info(">>assessment_management_attachments: Update Attachments <<")

            # 0. Parse the document ID
            doc_id = id.replace("_._", ":").format()

            # 1. Delete step
            doc_delete = True
            if 'delete' in request.form:

                # 1.1 Get the delete list
                raw_list = request.form.getlist('delete')

                if len(raw_list) > 0:
                    # 1.2 Parse raw data to files to be deleted
                    files_to_delete = []
                    for item in raw_list:
                        files_to_delete.extend(item.split(','))

                    # 1.3 Add attachment(s) to the document
                    doc_delete = database.delete_attachment(doc_id=doc_id,
                                                            file_list=files_to_delete)

            # 2. Add step
            doc_add = True
            if request.files:
                if len(request.files) > 0:

                    # 2.1 Generate the file list
                    file_list = []
                    for file in request.files.items():
                        file_list.append(
                            {'file_name': file[1].filename,
                             'content_type': file[1].mimetype,
                             'data': b64encode(file[1].read())
                             })

                    # 3.2 Add attachment(s) to the document
                    doc_add = database.add_attachment(doc_id=doc_id,
                                                      file_list=file_list)

            # 3. Return the result
            if doc_delete is not None and doc_add is not None:
                return jsonify({}), 200

            # 4. Something goes wrong to update
            return jsonify({}), 500

        if request.method == 'GET':
            logging.info(">>assessment_management_attachments: Download <<")

            # 2. Parse the document ID
            doc_id = id.replace("_._", ":").format()

            down_file = b64decode(database.get_attachment(doc_id=doc_id,
                                                          file_name=file_name))

            return down_file, 200, {'Content-Type': 'application/octet-stream'}

    except Exception as e:
        logging.error("** assessment_management_attachments: exception ** ")
        logging.exception(str(e))
        return jsonify({'status': 'Internal error'}), 500