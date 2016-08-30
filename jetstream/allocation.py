import logging

from django.conf import settings
from django.utils import timezone
from dateutil.parser import parse

from .exceptions import TASAPIException
from .api import tacc_api_post, tacc_api_get
from core.models.allocation_source import AllocationSource, UserAllocationSource

logger = logging.getLogger(__name__)


class TASAPIDriver(object):
    tacc_api = None
    allocation_list = []
    project_list = []
    user_project_list = []

    def __init__(self, tacc_api=None, resource_name='Jetstream'):
        if not tacc_api:
            tacc_api = settings.TACC_API_URL
        self.tacc_api = tacc_api
        self.resource_name = resource_name

    def clear_cache(self):
        self.user_project_list = []
        self.project_list = []
        self.allocation_list = []

    def get_all_allocations(self):
        if not self.allocation_list:
            self.allocation_list = self._get_all_allocations()
        return self.allocation_list

    def get_all_projects(self, resource_name='Jetstream'):
        if not self.project_list:
            self.project_list = self._get_all_projects()
        return self.project_list

    def find_projects_for(self, tacc_username, resource_name='Jetstream'):
        if not self.user_project_list:
            self.user_project_list = self.get_all_project_users(resource_name=resource_name)
        if not tacc_username:
            return self.user_project_list
        filtered_user_list = [p for p in self.user_project_list if tacc_username in p['users']]
        return filtered_user_list

    def get_all_project_users(self, resource_name='Jetstream'):
        if not self.user_project_list:
            self.project_list = self._get_all_projects()
            for project in self.project_list:
                project_users = self.get_project_users(project['id'])
                project['users'] = project_users
            self.user_project_list = self.project_list
        return self.user_project_list

    def get_username_for_xsede(self, xsede_username):
        path = '/v1/users/xsede/%s' % xsede_username
        url_match = self.tacc_api + path
        resp, data = tacc_api_get(url_match)
        try:
            if data['status'] != 'success':
                raise TASAPIException(
                    "NO valid username found for %s" % xsede_username)
            tacc_username = data['result']
            return tacc_username
        except ValueError as exc:
            raise TASAPIException("JSON Decode error -- %s" % exc)


    def report_project_allocation(self, username, project_name, su_total, start_date, end_date, queue_name, scheduler_id):
        """
        Send back a report
        """
        if not type(su_total) in [int, float]:
            raise Exception("SU total should be integer or float")
    
        post_data = {
            "sus": su_total,  # NOTE: This is likely to change in future v.
            "username": username,
            "project": project_name,
            "queueName": queue_name,
            "resource": self.resource_name,
            "schedulerId": scheduler_id,
            # Ex date format: "2014-12-01T19:25:43"
            "queueUTC": start_date.strftime("%Y-%m-%dT%H:%M:%S"),
            "startUTC": start_date.strftime("%Y-%m-%dT%H:%M:%S"),
            "endUTC": end_date.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    
        path = '/v1/jobs'
        url_match = self.tacc_api + path
        logger.debug("TAS_REQ: %s - POST - %s" % (url_match, post_data))
        resp = tacc_api_post(url_match, post_data)
        logger.debug("TAS_RESP: %s" % resp.__dict__)  # Overkill?
        try:
            data = resp.json()
            logger.debug("TAS_RESP - Data: %s" % data)
            resp_status = data['status']
        except ValueError:
            exc_message = ("Invalid Response - Expected 'status' in the json response: %s" % (resp.text,))
            logger.exception(exc_message)
            raise ValueError(exc_message)
    
        if resp_status != 'success' or resp.status_code != 200:
            exc_message = ("Invalid Response - Expected 200 and 'success' response: %s - %s" % (resp.status_code, resp_status))
            logger.exception(exc_message)
            raise Exception(exc_message)
    
        return data

    def get_allocation_project_id(self, allocation_id):
        allocation = self.get_allocation(allocation_id)
        if not allocation:
            return
        return allocation['projectId']

    def get_allocation_project_name(self, allocation_id):
        allocation = self.get_allocation(allocation_id)
        if not allocation:
            return
        return allocation['project']

    def get_project(self, project_id):
        filtered_list = [
            p for p in self.get_all_projects()
            if str(p['id']) == str(project_id)]
        if len(filtered_list) > 1:
            logger.error(">1 value found for project %s" % project_id)
        if filtered_list:
            return filtered_list[0]
        return None

    def get_allocation(self, allocation_id):
        filtered_list = [
            a for a in self.get_all_allocations()
            if str(a['id']) == str(allocation_id)]
        if len(filtered_list) > 1:
            logger.error(">1 value found for allocation %s" % allocation_id)
        if filtered_list:
            return filtered_list[0]
        return None

    def _get_all_allocations(self):
        """
        """
        path = '/v1/allocations/resource/%s' % self.resource_name
        allocations = {}
        url_match = self.tacc_api + path
        resp, data = tacc_api_get(url_match)
        try:
            _validate_tas_data(data)
            allocations = data['result']
            return allocations
        except ValueError as exc:
            raise TASAPIException("JSON Decode error -- %s" % exc)

    def _get_all_projects(self):
        """
        """
        path = '/v1/projects/resource/%s' % self.resource_name
        url_match = self.tacc_api + path
        resp, data = tacc_api_get(url_match)
        try:
            _validate_tas_data(data)
            projects = data['result']
            return projects
        except ValueError as exc:
            raise TASAPIException("JSON Decode error -- %s" % exc)

    def _get_tacc_user(self, user):
        try:
            tacc_user = self.get_username_for_xsede(
                user.username)
        except:
            logger.info("User: %s has no tacc username" % user.username)
            tacc_user = user.username
        return tacc_user

    def get_project_users(self, project_id):
        path = '/v1/projects/%s/users' % project_id
        url_match = self.tacc_api + path
        resp, data = tacc_api_get(url_match)
        user_names = []
        try:
            _validate_tas_data(data)
            users = data['result']
            for user in users:
                username = user['username']
                user_names.append(username)
            return user_names
        except ValueError as exc:
            if raise_exception:
                raise TASAPIException("JSON Decode error -- %s" % exc)
            logger.info( exc)
        except Exception as exc:
            if raise_exception:
                raise
            logger.info( exc)
        return user_names

    

    def get_user_allocations(self, username, resource_name='Jetstream', raise_exception=True):
        path = '/v1/projects/username/%s' % username
        url_match = self.tacc_api + path
        resp, data = tacc_api_get(url_match)
        user_allocations = []
        try:
            _validate_tas_data(data)
            projects = data['result']
            for project in projects:
                allocations = project['allocations']
                for allocation in allocations:
                    if allocation['resource'] == resource_name:
                        user_allocations.append( (project, allocation) )
            return user_allocations
        except ValueError as exc:
            if raise_exception:
                raise TASAPIException("JSON Decode error -- %s" % exc)
            logger.info( exc)
        except Exception as exc:
            if raise_exception:
                raise
            logger.info( exc)
        return None



def get_or_create_allocation_source(api_allocation, update_source=False):
    try:
        source_name = "%s" % (api_allocation['project'],)
        source_id = api_allocation['id']
        compute_allowed = int(api_allocation['computeAllocated'])
    except (TypeError, KeyError, ValueError):
        raise TASAPIException("Malformed API Allocation - Missing keys in dict: %s" % api_allocation)

    try:
        source = AllocationSource.objects.get(
            source_id=source_id
        )
        if update_source:
            if compute_allowed != source.compute_allowed:
                #FIXME: Here would be a *great* place to create a new event to "ignore" all previous allocation_source_`threshold_met/threshold_enforced`
                source.compute_allowed = compute_allowed
            source.name = source_name
            source.save()
        return source, False
    except AllocationSource.DoesNotExist:
        source = AllocationSource.objects.create(
            name=source_name,
            compute_allowed=compute_allowed,
            source_id=source_id
        )
        return source, True


def fill_allocation_sources(force_update=False):
    driver = TASAPIDriver()
    allocations = driver.get_all_allocations()
    create_list = []
    for api_allocation in allocations:
        obj, created = get_or_create_allocation_source(
            api_allocation, update_source=force_update)
        if created:
            create_list.append(obj)
    return len(create_list)


def collect_users_without_allocation(driver):
    from core.models import AtmosphereUser
    missing = []
    for user in AtmosphereUser.objects.order_by('username'):
        tacc_user = driver._get_tacc_user(user)
        user_allocations = driver.get_user_allocations(
            tacc_user, raise_exception=False)
        if not user_allocations:
            missing.append(user)
    return missing


def fill_user_allocation_sources():
    from core.models import AtmosphereUser
    driver = TASAPIDriver()
    allocation_resources = {}
    for user in AtmosphereUser.objects.order_by('username'):
        resources = fill_user_allocation_source_for(driver, user)
        allocation_resources[user.username] = resources
    return allocation_resources

def fill_user_allocation_source_for(driver, user, force_update=True):
    tacc_user = driver._get_tacc_user(user)
    projects = driver.find_projects_for(tacc_user)
    allocation_resources = []
    for api_project in projects:
        api_allocation = select_valid_allocation(api_project['allocations'])
        if not api_allocation:
            logger.error("API shows no valid allocation exists for project %s" % api_project)
            continue
        allocation_source, _ = get_or_create_allocation_source(
            api_allocation, update_source=force_update)
        resource, _ = UserAllocationSource.objects.get_or_create(
            allocation_source=allocation_source,
            user=user)
        allocation_resources.append(allocation_source)
    return allocation_resources

def select_valid_allocation(allocation_list):
    now = timezone.now()
    for allocation in allocation_list:
        start_timestamp = allocation['start']
        end_timestamp = allocation['end']
        status = allocation['status']
        start_date = parse(start_timestamp)
        end_date = parse(end_timestamp)
        if start_date >= now or end_date <= now:
           logger.info("Skipping Allocation %s because its dates are outside the range for timezone.now()" % allocation)
           continue
        if status.lower() != 'active':
           logger.info("Skipping Allocation %s because its listed status is NOT 'active'" % allocation)
           continue
        return allocation
    return None


def _validate_tas_data(data):
    if not data or 'status' not in data or 'result' not in data:
        raise TASAPIException(
            "API is returning a malformed response - "
            "Expected json object including "
            "a 'status' key and a 'result' key. - "
            "Received: %s" % data)
    if data['status'] != 'success':
        raise TASAPIException(
            "API is returning an unexpected status %s - "
            "Received: %s"
            % (data['status'], data)
        )
    return True

