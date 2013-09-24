# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
NephoScale Cloud driver (http://www.nephoscale.com)
API documentation: http://docs.nephoscale.com
Created by Markos Gogoulos (https://mist.io)
"""

import base64
import sys
import string
import random
import time

try:
    import simplejson as json
except:
    import json

from libcloud.utils.py3 import httplib
from libcloud.utils.py3 import b
from libcloud.utils.py3 import urlencode

from libcloud.compute.providers import Provider
from libcloud.common.base import JsonResponse, ConnectionUserAndKey
from libcloud.compute.types import NodeState, InvalidCredsError
from libcloud.compute.base import Node, NodeDriver, NodeImage, NodeSize, NodeLocation

API_HOST = "api.nephoscale.com"

NODE_STATE_MAP = {
    'on': NodeState.RUNNING,
    'off': NodeState.UNKNOWN,
    'unknown': NodeState.UNKNOWN,    
}

VALID_RESPONSE_CODES = [httplib.OK, httplib.ACCEPTED, httplib.CREATED, httplib.NO_CONTENT]

class NephoscaleResponse(JsonResponse):
    """
    Nephoscale API Response
    """

    def parse_error(self):
        if self.status == 401:
            raise InvalidCredsError('Authorization Failed')
        if self.status == 404:
            raise Exception("The resource you are looking for is not found.")

        return self.body

    def success(self):
        return self.status in VALID_RESPONSE_CODES

class NephoscaleConnection(ConnectionUserAndKey):
    """
    Nephoscale connection class.
    Authenticates to the API through Basic Authentication with username/password
    """
    host = API_HOST
    responseCls = NephoscaleResponse

    def add_default_headers(self, headers):
        """
        Add parameters that are necessary for every request
        """        
        user_b64 = base64.b64encode(b('%s:%s' % (self.user_id, self.key)))
        headers['Authorization'] = 'Basic %s' % (user_b64.decode('utf-8'))
        return headers

class NephoscaleNodeDriver(NodeDriver):
    """
    Nephoscale node driver class.

    >>> from libcloud.compute.types import Provider
    >>> from libcloud.compute.providers import get_driver
    >>> driver = get_driver('nephoscale')
    >>> conn = driver('nepho_user','nepho_password')
    >>> conn.list_nodes()
    """

    type = Provider.NEPHOSCALE
    api_name = 'nephoscale'    
    name = 'NephoScale'
    website = 'http://www.nephoscale.com'
    connectionCls = NephoscaleConnection
    features = {'create_node': ['ssh_key']}    

    def __init__(self, *args, **kwargs):
        """Instantiate the driver with nephoscale's user and password
        """    
        super(NephoscaleNodeDriver, self).__init__(*args, **kwargs)

    def list_locations(self):
        result = self.connection.request('/datacenter/').object    
        locations = []
        for value in result.get('data', []):
            location = NodeLocation(id=value.get('id'),
                                    name=value.get('name'),
                                    country='US',
                                    driver=self.connection.driver)
            locations.append(location)
        return locations

    def list_images(self):
        """
        List available Images
        """
        result = self.connection.request('/image/server/').object
        images = []
        for value in result.get('data', []):
            extra = {'architecture': value.get('architecture'),
                     'disks': value.get('disks'),
                     'billable_type': value.get('billable_type'), 
                     'pcpus': value.get('pcpus'), 
                     'cores': value.get('cores'),
                     'uri': value.get('uri'), 
                     'storage': value.get('storage'), 
            }
            image = NodeImage(id=value.get('id'), name=value.get('friendly_name'),
                  driver=self.connection.driver, extra=extra)
            images.append(image)
        return images

    def list_sizes(self):
        """
        List available Sizes
        """
        result = self.connection.request('/server/type/cloud/').object
        sizes = []
        for value in result.get('data', []):
            size = NodeSize(id=value.get('id'), 
                            name=value.get('friendly_name'),
                            ram=value.get('ram'), 
                            disk=value.get('storage'),
                            bandwidth=None,
                            price=self._get_size_price(size_id=str(value.get('id'))),
                            driver=self.connection.driver)
            sizes.append(size)
        
        return sorted(sizes, key=lambda k: k.price)


    def list_nodes(self):
        """
        List available Nodes
        """    
        result = self.connection.request('/server/cloud/').object
        nodes = [self._to_node(value) for value in result.get('data', [])]
        return nodes

    def rename_node(self, node, name, hostname=None):
        "rename a cloud server, optionally specify hostname too"
        data = {'name': name}
        if hostname:
            data['hostname'] = hostname    
        params = urlencode(data)                   
        result = self.connection.request('/server/cloud/%s/' % node.id, data=params, method='PUT').object
        return result.get('response') in VALID_RESPONSE_CODES

    def reboot_node(self, node):
        "reboot a running node"
        result = self.connection.request('/server/cloud/%s/initiator/restart/' % node.id, method='POST').object
        return result.get('response') in VALID_RESPONSE_CODES
       
    def ex_start_node(self, node):
        "start a stopped node"    
        result = self.connection.request('/server/cloud/%s/initiator/start/' % node.id, method='POST').object
        return result.get('response') in VALID_RESPONSE_CODES

    def ex_stop_node(self, node):
        "stop a running node"    
        result = self.connection.request('/server/cloud/%s/initiator/stop/' % node.id, method='POST').object
        return result.get('response') in VALID_RESPONSE_CODES

    def destroy_node(self, node):
        "destroy a node"        
        result = self.connection.request('/server/cloud/%s/' % node.id, method='DELETE').object
        return result.get('response') in VALID_RESPONSE_CODES

    def list_all_keys(self, key_group=None):
        """list console and server keys
           if key_group is specified, show keys with this key_group only
           eg key_group=4 for console password keys
        """
        result = self.connection.request('/key/').object
        keys = [self._to_ssh_key(value) for value in result.get('data', [])]
        if key_group:
            keys = [key for key in keys if key.get('key_group', '') == key_group]        
        return keys

    def list_ssh_keys(self):
        "list ssh keys keys"  
        result = self.connection.request('/key/sshrsa/').object
        keys = [self._to_ssh_key(value) for value in result.get('data', [])]
        return keys

    def list_password_keys(self):
        "list password console and password server keys"
        result = self.connection.request('/key/password/').object
        keys = [self._to_ssh_key(value) for value in result.get('data', [])]
        return keys

    def add_ssh_key(self, name, public_key, key_group=1):
        """Add an ssh key, given the public key and name
           Returns the id of the created ssh key
        """    
        data = {
            'name': name,
            'public_key': public_key,
            'key_group': key_group #key_group: The group for the key, where Server=1 and Console=4
        }    
        params = urlencode(data)
        try:
            result = self.connection.request('/key/sshrsa/', data=params, method='POST').object
        except Exception:
            e = sys.exc_info()[1]
            raise e
        return result.get('data', {}).get('id','')

    def add_password_key(self, name, password=None, key_group=4):
        """Add a password key, given the name and password
           If password not specified, create a random password with lowercase strings and numbers
           
           Returns the id of the created ssh key
        """        
        if not password:
            password = self.random_password()            
        data = {
            'name': name,
            'password': password,
            'key_group': key_group #key_group: The group for the key, where Server=1 and Console=4
        }    
        params = urlencode(data)
        try:
            result = self.connection.request('/key/password/', data=params, method='POST').object
        except Exception:
            e = sys.exc_info()[1]
            raise e
        return result.get('data', {}).get('id','')

    def delete_ssh_key(self, key_id):
        """Delete an ssh key, given it's id
        """
        try:
            result = self.connection.request('/key/sshrsa/%s/' % key_id, method='DELETE').object
        except Exception:
            e = sys.exc_info()[1]
            raise e        
        return result.get('response') in VALID_RESPONSE_CODES

    def delete_password_key(self, key_id):
        """Delete a password, given it's id
        """
        try:
            result = self.connection.request('/key/password/%s/' % key_id, method='DELETE').object
        except Exception:
            e = sys.exc_info()[1]
            raise e        
        return result.get('response') in VALID_RESPONSE_CODES

    def create_node(self, **kwargs):   
        """Creates the node, and sets the ssh key, console key
        NephoScale will respond with a 200-200 response after sending a valid request
        We then ask a few times until the server is created and assigned a public IP address, so that
        deploy_node can be run         

        >>> from libcloud.compute.types import Provider
        >>> from libcloud.compute.providers import get_driver
        >>> driver = get_driver('nephoscale')
        >>> conn = driver('nepho_user','nepho_password')
        >>> conn.list_nodes()
        >>> name = 'staging-server'
        >>> size = conn.list_sizes()[0]
        <NodeSize: id=27, name=CS025 - 0.25GB, 10GB, ram=256 disk=15 bandwidth=None price=0.0 driver=NephoScale ...>
        >>> image = conn.list_images()[9]
        <NodeImage: id=49, name=Linux Ubuntu Server 10.04 LTS 64-bit, driver=NephoScale  ...>
        >>> server_key_dict = conn.list_all_keys(1)[0]
        {u'create_time': u'2013-09-17 04:55:42',
        u'id': 70867,
        u'key_group': 1,
        u'key_type': 2,
        u'name': u'nephoscalekey',
        u'uri': u'https://api.nephoscale.com/key/sshrsa/70867/'}        
        >>> server_key = server_key_dict.get('id')
        70867
        >>> console_key_dict = conn.list_all_keys(4)[0]
        {u'create_time': u'2013-09-17 07:30:09',
        u'id': 70907,
        u'key_group': 4,
        u'key_type': 1,
        u'name': u'apo-mistio_07a6b018',
        u'uri': u'https://api.nephoscale.com/key/password/70907/'}
        >>> console_key = console_key_dict.get('id')        
        70907
        node = conn.create_node(name=name, size=size, image=image, console_key=console_key, server_key=server_key)
        
        We can also create an ssh key, plus a console key and deploy node with them
        >>> server_key = conn.add_ssh_key(name, key)
        71211        
        >>> console_key = conn.add_password_key(name)
        71213
        """    
        try: 
            name = kwargs.get('name')
            if not name:
                raise Exception("Name cannot be blank")      
            hostname = kwargs.get('hostname', name)
            service_type = kwargs.get('size')
            if not service_type:
                raise Exception("Service type cannot be blank")      
            service_type = service_type.id
            image = kwargs.get('image')
            if not image:
                raise Exception("Image cannot be blank")      
            image = image.id
            server_key = kwargs.get('server_key', '')
            console_key = kwargs.get('console_key', '')            
        except Exception:
            e = sys.exc_info()[1]
            raise Exception("Error on create node: %s" % e)      
        
        data = {'name': name, 
                'hostname': hostname,
                'service_type': service_type,
                'image': image,
                'server_key': server_key,
                'console_key': console_key                
        }
        
        params = urlencode(data)
        try:
            node = self.connection.request('/server/cloud/', data=params, method='POST')        
        except Exception:
            e = sys.exc_info()[1]
            raise Exception("Failed to create node %s" % e)   
        node = Node(id='', name=name, state='', public_ips='', private_ips='', driver=self.connection.driver)      
        #try to get the created node public ips, for use in deploy_node 
        #At this point we don't have the id of the newly created Node, so search name in nodes
        LOGIN_ATTEMPTS = 20
        created_node = False
        while LOGIN_ATTEMPTS > 0:
            nodes = self.list_nodes()
            created_node = [c_node for c_node in nodes if c_node.name == name]
            if created_node:
                return created_node[0]
            else:
                time.sleep(10)                     
                LOGIN_ATTEMPTS-=1
        return node                                 

    def _to_node(self, data):
        """Convert node in Node instances
        """
    
        state = NODE_STATE_MAP.get(data.get('power_status'), '4')
        public_ips = []
        private_ips = []
        ip_addresses = data.get('ipaddresses', '')
        #E.g. "ipaddresses": "198.120.14.6, 10.132.60.1"
        if ip_addresses:
            ip_addresses_list = ip_addresses.split(',')
            for ip in ip_addresses_list:
                ip = ip.replace(' ','')
                if ip.startswith('10.') or ip.startswith('192.168'):
                    private_ips.append(ip)
                else:
                    public_ips.append(ip)
        extra = {'zone_data': data.get('zone'), 
                 'zone': data.get('zone', {}).get('name'), 
                 'image': data.get('image', {}).get('friendly_name'),
                 'create_time': data.get('create_time'), 
                 'network_ports': data.get('network_ports'), 
                 'is_console_enabled': data.get('is_console_enabled'),
                 'service_type': data.get('service_type', {}).get('friendly_name'),                  
                 'hostname': data.get('hostname')
        }

        node = Node(id=data.get('id'), name=data.get('name'), state=state,
                    public_ips=public_ips, private_ips=private_ips,
                    driver=self.connection.driver, extra=extra)
        return node

    def _to_ssh_key(self, data):
        return data
        
    def random_password(self, size=8, chars=string.ascii_lowercase + string.digits):
        return ''.join(random.choice(chars) for x in range(size))
