"""
Python classes for Nopticon
"""

from enum import Enum
import ipaddress
import json

class PrefSummary:
    def __init__(self, summary_json, sigfigs=9):
        self._summary=json.loads(summary_json)
        self._sigfigs = sigfigs

        self._preferences = []

        if 'path-preferences' in self._summary:
        
            for pref in self._summary['path-preferences']:
                if pref['rank'] > 0.5:
                    self._preferences.append(PathPreferencePolicy({
                        'flow' : pref['flow'],
                        'paths' : [
                            pref['x-path'],
                            pref['y-path'],
                        ]
                    }))
                else:
                    # print("DISCARD", PathPreferencePolicy({
                    #     'flow' : pref['flow'],
                    #     'paths' : [
                    #         pref['x-path'],
                    #         pref['y-path'],
                    #     ]
                    # }), pref["rank"])
                    continue

    def preferences(self):
        return self._preferences

    def __str__(self):
        return "\n".join(str(p) for p in preferences)

class ReachSummary:
    def __init__(self, summary_json, sigfigs=8):
        self._summary = json.loads(summary_json)
        self._sigfigs = sigfigs

        # Extract edges
        self._edges = {}
        for flow in self._summary['reach-summary']:
            flow_prefix = ipaddress.ip_network(flow['flow'])
            flow_edges = {}
            for edge_details in flow['edges']:
                edge = (edge_details['source'], edge_details['target'])
                flow_edges[edge] = edge_details
            self._edges[flow_prefix] = flow_edges

    def get_flows(self):
        return self._edges.keys()

    def get_edges(self, flow):
        if flow not in self._edges:
            return {}
        return self._edges[flow]

    def get_edge_rank(self, flow, edge):
        if edge not in self.get_edges(flow):
            return None
        return round(self.get_edges(flow)[edge]['rank-0'], self._sigfigs)

    def get_flowedges(self):
        return [(f,e) for f in self.get_flows() for e in self.get_edges(f)]

    def to_policy_set(self, show_implied=False, flow_str=None, threshold=0):
        policies = set()
        for flow in self.get_flows():
            if flow_str is not None and str(flow) != flow_str:
                continue
            for edge in self.get_edges(flow):
                is_implied = self.edge_is_implied(flow, edge)
                rank = self.get_edge_rank(flow,edge)
                if rank >= threshold:
                    if (show_implied and is_implied) or not is_implied:
                        policies.add(ReachabilityPolicy({
                            'flow' : flow,
                            'source': edge[0],
                            'target': edge[1]
                        }))
        return policies

    def is_insight(self,flow, edge, cluster=False, threshold=None, implied=False):
        if cluster and not self.is_cluster_accepted(flow, edge):
            return False

        if threshold is not None and not self.is_above_threshold(threshold, flow, edge):
            return False

        if implied and self.edge_is_implied(flow,edge):
            # print("IMPLIED:", flow, edge)
            return False

        return True
            
    def clear(self):
        for flow,edge in self.get_flowedges():
            edge_data = self.get_edges(flow)[edge]
            if 'T' in edge_data:
                del edge_data['T']

            if 'C' in edge_data:
                del edge_data['C']

            if 'implied_by' in edge_data:
                del edge_data['implied_by']
        return
    
    def mark_above_threshold(self, t, flow, edge):
        self.get_edges(flow)[edge]['T'] = t

    def is_above_threshold(self, t, flow, edge):
        return 'T' in self.get_edges(flow)[edge] and\
            (t is None or self.get_edges(flow)[edge]['T'] >= t)

    def mark_cluster_accepted(self, flow, edge):
        self.get_edges(flow)[edge]['C'] = True

    def mark_cluster_unaccepted(self,flow, edge):
        self.get_edges(flow)[edge]['C'] = False


    def is_cluster_accepted(self, flow, edge):
        edgedata = self.get_edges(flow)[edge]
        return 'C' in edgedata and edgedata['C']
    
    
    def mark_edge_implied_by(self, flow, premise, conclusion):
        if conclusion in self.get_edges(flow):
            # the conclusion is implied by EACH if the contents of the implied_by list
            if 'implied_by' in self.get_edges(flow)[conclusion]:
                self.get_edges(flow)[conclusion]['implied_by'].append(list(premise))
            else:
                self.get_edges(flow)[conclusion]['implied_by'] = [list(premise)]
            # print("\t",premise, "==>", conclusion)
            return True
        else:
            return False

    def edge_is_implied(self, flow, edge):
        return edge in self.get_edges(flow)\
            and 'implied_by' in self.get_edges(flow)[edge]\
            and len(self.get_edges(flow)[edge]['implied_by']) > 0

    def get_implicators(self, flow, edge):
        if self.edge_is_implied(flow,edge):
            return self.get_edges(flow)[edge]['implied_by']
        else:
            return []
    
class LinkSummary:
    def __init__(self, summary_json):
        self._summary = json.loads(summary_json)

        self._links = {}
        for flow in self._summary['flows']:
            flow_prefix = ipaddress.ip_network(flow['flow'])
            flow_links = {}
            for link in flow['links']:
                flow_links[link['source']] = link['target']
            self._links[flow_prefix] = flow_links

    def get_flows(self):
        return self._links.keys()

    def get_links(self, flow):
        if flow not in self._links:
            return {}
        return self._links[flow]

    def get_targets(self, flow, source):
        if source not in self.get_links(flow):
            return []
        return self.get_links(flow)[source]

class CommandType(Enum):
    PRINT_LOG = 0
    RESET_NETWORK_SUMMARY = 1
    REFRESH_NETWORK_SUMMARY = 2

class Command():
    def __init__(self, cmd_type):
        self._type = cmd_type

    def json(self):
        cmd = {'Command' : {'Opcode' : self._type.value}}
        if self._type == CommandType.REFRESH_NETWORK_SUMMARY:
            cmd['Command']['Timestamp'] = self._timestamp
        return json.dumps(cmd)

    @classmethod
    def print_log(cls):
        return cls(CommandType.PRINT_LOG)

    @classmethod
    def reset_summary(cls):
        return cls(CommandType.RESET_NETWORK_SUMMARY)

    @classmethod
    def refresh_summary(cls, timestamp):
        obj = cls(CommandType.REFRESH_NETWORK_SUMMARY)
        obj._timestamp = timestamp
        return obj

"""Convert policies JSON to a list of Policy objects"""
def parse_policies(policies_json):
    policies_dict = json.loads(policies_json)
    policies = []
    for policy_dict in policies_dict['policies']:
        if policy_dict['type'] == PolicyType.REACHABILITY.value:
            policies.append(ReachabilityPolicy(policy_dict))
        elif policy_dict['type'] == PolicyType.PATH_PREFERENCE.value:
            policies.append(PathPreferencePolicy(policy_dict))
    return policies

class PolicyType(Enum):
    REACHABILITY = "reachability"
    PATH_PREFERENCE = "path-preference"

class Policy:
    def __init__(self, typ, policy_dict):
        self._type = typ
        self._flow = ipaddress.ip_network(policy_dict['flow'])

    def isType(self, typ):
        return self._type == typ

    def flow(self):
        return self._flow

class ReachabilityPolicy(Policy):
    def __init__(self, policy_dict):
        super().__init__(PolicyType.REACHABILITY, policy_dict)
        self._source = policy_dict['source'][:10]
        self._target = policy_dict['target'][:10]

    def edge(self):
        return (self._source, self._target)

    def __str__(self):
        return '%s %s->%s' % (self._flow, self._source, self._target)

    def __hash__(self):
        return hash((self._flow, self._source, self._target))

    def __eq__(self, other):
        return ((self._flow, self._source, self._target)
                == (other._flow, other._source, other._target))

class PathPreferencePolicy(Policy):
    def __init__(self, policy_dict):
        super().__init__(PolicyType.PATH_PREFERENCE, policy_dict)
        self._paths = policy_dict['paths']
        for path in self._paths:
            for i in range(0, len(path)):
                path[i] = path[i][:10]

    def toReachabilityPolicy(self):
        return ReachabilityPolicy({'flow' : self._flow,
                'source' : self._paths[0][0], 'target' : self._paths[0][-1]})

    def toImpliedReachabilityPolicies(self, waypoints_only=False):
        if (waypoints_only):
            waypoints = set(self._paths[0])
            for p in self._paths:
                waypoints = waypoints.intersection(set(p))
            return [ReachabilityPolicy({'flow' : self._flow, 
                    'source': self._paths[0][0],
                    'target': w}) for w in waypoints] + \
                    [ReachabilityPolicy({'flow' : self._flow,
                    'source': w,
                    'target': self._paths[0][-1]}) for w in waypoints]
        else:
            return  [ReachabilityPolicy({'flow' : self._flow,
                                        'source': n,
                                        'target': m})
                    for p in self._paths
                    for i,n in enumerate(p)
                    for m in p[i+1:]] 

    def __eq__(self, other):
        if self._flow != other._flow:
            return False
        
        for pp in self._paths:
            pp_in_other = False
            for op in other._paths:
                if pp == op:
                    pp_in_other = True
            if not pp_in_other:
                return False

        for op in other._paths:
            op_in_self = False
            for pp in self._paths:
                if op == pp:
                    op_in_self = True
            if not op_in_self:
                return False

        return True
    
    def __str__(self):
        return '%s %s' % (self._flow,
                ' > '.join(['->'.join(path) for path in self._paths]))

"""Convert rdns JSON to a dictionary of IPs to router names"""
def parse_rdns(rdns_json):
    routers_dict = json.loads(rdns_json)
    rdns = {}
    for router_dict in routers_dict['routers']:
        name = router_dict['name']
        for iface_ip in router_dict['ifaces']:
            rdns[ipaddress.ip_address(iface_ip)] = name
    return rdns
