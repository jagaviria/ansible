# (c) 2019 Piotr Wojciechowski (@wojciechowskipiotr) <piotr@it-playground.pl>
# (c) Thierry Bouvet (@tbouvet)
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import json

try:
    from docker.errors import APIError
except ImportError:
    # missing docker-py handled in ansible.module_utils.docker.common
    pass

from ansible.module_utils._text import to_native
from ansible.module_utils.docker.common import AnsibleDockerClient


class AnsibleDockerSwarmClient(AnsibleDockerClient):

    def __init__(self, **kwargs):
        super(AnsibleDockerSwarmClient, self).__init__(**kwargs)

    def get_swarm_node_id(self):
        """
        Get the 'NodeID' of the Swarm node or 'None' if host is not in Swarm. It returns the NodeID
        of Docker host the module is executed on
        :return:
            NodeID of host or 'None' if not part of Swarm
        """

        try:
            info = self.info()
        except APIError as exc:
            self.fail(msg="Failed to get node information for %s" % to_native(exc))

        if info:
            json_str = json.dumps(info, ensure_ascii=False)
            swarm_info = json.loads(json_str)
            if swarm_info['Swarm']['NodeID']:
                return swarm_info['Swarm']['NodeID']
        return None

    def check_if_swarm_node(self, node_id=None):
        """
        Checking if host is part of Docker Swarm. If 'node_id' is not provided it reads the Docker host
        system information looking if specific key in output exists. If 'node_id' is provided then it tries to
        read node information assuming it is run on Swarm manager. The get_node_inspect() method handles exception if
        it is not executed on Swarm manager

        :param node_id: Node identifier
        :return:
            bool: True if node is part of Swarm, False otherwise
        """

        if node_id is None:
            try:
                info = self.info()
            except APIError:
                self.fail(msg="Failed to get host information.")

            if info:
                json_str = json.dumps(info, ensure_ascii=False)
                swarm_info = json.loads(json_str)
                if swarm_info['Swarm']['NodeID']:
                    return True
            return False
        else:
            try:
                node_info = self.get_node_inspect(node_id=node_id)
            except APIError:
                return

            if node_info['ID'] is not None:
                return True
            return False

    def check_if_swarm_manager(self):
        """
        Checks if node role is set as Manager in Swarm. The node is the docker host on which module action
        is performed. The inspect_swarm() will fail if node is not a manager

        :return: True if node is Swarm Manager, False otherwise
        """

        try:
            self.inspect_swarm()
            return True
        except APIError:
            return False

    def fail_task_if_not_swarm_manager(self):
        """
        If host is not a swarm manager then Ansible task on this host should end with 'failed' state
        """
        if not self.check_if_swarm_manager():
            self.fail(msg="This node is not a manager.")

    def check_if_swarm_worker(self):
        """
        Checks if node role is set as Worker in Swarm. The node is the docker host on which module action
        is performed. Will fail if run on host that is not part of Swarm via check_if_swarm_node()

        :return: True if node is Swarm Worker, False otherwise
        """

        if self.check_if_swarm_node() and not self.check_if_swarm_manager():
            return True
        return False

    def check_if_swarm_node_is_down(self, node_id=None):
        """
        Checks if node status on Swarm manager is 'down'. If node_id is provided it query manager about
        node specified in parameter, otherwise it query manager itself. If run on Swarm Worker node or
        host that is not part of Swarm it will fail the playbook

        :param node_id: node ID or name, if None then method will try to get node_id of host module run on
        :return:
            True if node is part of swarm but its state is down, False otherwise
        """

        if node_id is None:
            node_id = self.get_swarm_node_id()

        node_info = self.get_node_inspect(node_id=node_id)
        if node_info['Status']['State'] == 'down':
            return True
        return False

    def get_node_inspect(self, node_id=None, skip_missing=False):
        """
        Returns Swarm node info as in 'docker node inspect' command about single node

        :param skip_missing: if True then function will return None instead of failing the task
        :param node_id: node ID or name, if None then method will try to get node_id of host module run on
        :return:
            Single node information structure
        """

        if node_id is None:
            node_id = self.get_swarm_node_id()

        if node_id is None:
            self.fail(msg="Failed to get node information.")

        try:
            node_info = self.inspect_node(node_id=node_id)
        except APIError as exc:
            if exc.status_code == 503:
                self.fail(msg="Cannot inspect node: To inspect node execute module on Swarm Manager")
            if exc.status_code == 404:
                if skip_missing is False:
                    self.fail(msg="Error while reading from Swarm manager: %s" % to_native(exc))
                else:
                    return None
        except Exception as exc:
            self.module.fail_json(msg="Error inspecting swarm node: %s" % exc)

        json_str = json.dumps(node_info, ensure_ascii=False)
        node_info = json.loads(json_str)
        return node_info

    def get_all_nodes_inspect(self):
        """
        Returns Swarm node info as in 'docker node inspect' command about all registered nodes

        :return:
            Structure with information about all nodes
        """
        try:
            node_info = self.nodes()
        except APIError as exc:
            if exc.status_code == 503:
                self.fail(msg="Cannot inspect node: To inspect node execute module on Swarm Manager")
            self.fail(msg="Error while reading from Swarm manager: %s" % to_native(exc))
        except Exception as exc:
            self.module.fail_json(msg="Error inspecting swarm node: %s" % exc)

        json_str = json.dumps(node_info, ensure_ascii=False)
        node_info = json.loads(json_str)
        return node_info

    def get_all_nodes_list(self, output='short'):
        """
        Returns list of nodes registered in Swarm

        :param output: Defines format of returned data
        :return:
            If 'output' is 'short' then return data is list of nodes hostnames registered in Swarm,
            if 'output' is 'long' then returns data is list of dict containing the attributes as in
            output of command 'docker node ls'
        """
        nodes_list = []

        nodes_inspect = self.get_all_nodes_inspect()
        if nodes_inspect is None:
            return None

        if output == 'short':
            for node in nodes_inspect:
                nodes_list.append(node['Description']['Hostname'])
        elif output == 'long':
            for node in nodes_inspect:
                node_property = {}

                node_property.update({'ID': node['ID']})
                node_property.update({'Hostname': node['Description']['Hostname']})
                node_property.update({'Status': node['Status']['State']})
                node_property.update({'Availability': node['Spec']['Availability']})
                if 'ManagerStatus' in node:
                    if node['ManagerStatus']['Leader'] is True:
                        node_property.update({'Leader': True})
                    node_property.update({'ManagerStatus': node['ManagerStatus']['Reachability']})
                node_property.update({'EngineVersion': node['Description']['Engine']['EngineVersion']})

                nodes_list.append(node_property)
        else:
            return None

        return nodes_list
