#! /usr/bin/python3

from itertools import combinations
from nopticon import ReachSummary, PolicyType, parse_policies
from argparse import ArgumentParser

class EnhancedReachSummary(nopticon.ReachSummary):
    def __init__(self, summary_json, sigfigs):
        super().__init__(summary_json, sigfigs)

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

class Topo:
    def __init__(self, topo_str):
        self._links = {}
        for line in topo_str.split('\n'):
            words = line.split(' ')
            if words[0] == "link":
                source = words[1].split(':')[0]
                target = words[2].split(':')[0]
                key = min(source, target)
                val = max(source, target)
                if key in self._links:
                    self._links[key].add(val)
                else:
                    self._links[key] = set([val])

    def all_nodes(self):
        nodes = set(self._links.keys())
        for valset in self._links.values():
            nodes = nodes.union(valset)
        return nodes

    def links(self):
        return set([(s,t)
                    for s,ts in self._links.items()
                    for t in ts])
        
    
    def _normalize(self, src, tgt):
        return (min(src,tgt), max(src,tgt))
                    
    def link_exists(self, source, target):
        key, val = self._normalize(source,target)
        return key in self._links and val in self._links[key]

class RestrictedGraph:
    def __init__(self, reach, topo, threshold):
        self._reach = reach
        self._topo = topo
        self._threshold = threshold

    def all_node_sets_between(self, source, target):
        usable_nodes = self._topo.all_nodes().difference(set([source,target]))
        return combinations(usable_nodes, len(usable_nodes))

    def does_separate(self, nodes, flow, source, target):
        next_hop = {}
        for (s,t) in self._reach.get_edges(flow).keys():
            if self._topo.link_exists(s,t) and round(self._reach.get_edge_rank(flow,(s,t)),2) > 0:
                if s in next_hop:
                    next_hop[s].add(t)
                else:
                    next_hop[s] = set([t])
                    
        seen = set()
        worklist = [source]
        while len(worklist) > 0:
            v = worklist[0]
            seen.add(v)
            if v == target:
                return False
            worklist += next_hop[v]

        return True
        
    
    def separate_all(self, flow, source, target):
        separators = []
        for node_set in self.all_node_sets_between(source, target):
            if self.does_separate(node_set, flow, source, target):
                separators.append(node_set)

        minimal_separators = []
        for s in separators:
            minimal = True
            for p in separators:
                if s != p and s.issuperset(p):
                    minimal = False
                    break
            if minimal:
                minimal_separators.append(s)
            else:
                continue
        return minimal_separators

    def separate(self, flow, source, target):
        separator = set()
        edges = self._reach.get_edges(flow)
        rank = lambda e: round(self._reach.get_edge_rank(flow,e),2)
        # inferred_edges = {e : d for e : d in edges.items()
        #                   if rank(e) >= self.threshold}
        physical_edges = self._topo.links()
        # if str(flow) == "3.0.0.0/24" and source == "leaf3_0" and target == "agg0_1":
        #     print("Separating", source, "and", target)
        # print(physical_edges)
        
        ## Compute _Close_ Separator Set in physical_edges
        # get successors S of source
        successors = set([tgt for (src, tgt) in physical_edges
                          if src == source]).union(
                                  set([tgt for tgt, src in physical_edges
                                       if src ==source]))

        # print("SUCCESSORS of", source, successors)
        
        # Compute Set of Nodes R that reach target, (not including those nodes in S)
        reach = set([ target ])
        separator = set()
        old_size = 0
        while len(reach) > old_size:
            old_size = len(reach)
            for (src, tgt) in physical_edges:
                if tgt in reach:
                    assert(tgt not in successors)
                    if src in successors:
                        # print("ADD-SRC", src)
                        separator.add(src)
                    else:
                        reach.add(src)
                if src in reach:
                    assert(src not in successors)
                    if tgt in successors:
                        # print("ADD-TGT", tgt)
                        separator.add(tgt)
                    else:
                        reach.add(tgt)
            # print(separator)
            size = len(reach)

        # if str(flow) == "3.0.0.0/24" and source == "leaf3_1" and target == "agg0_1":
        #    print(source, target, "separated by:", separator)
        return [separator]


    def rec_separate(self,flow, sources, targets):
        separator = set()
        edges = self._reach.get_edges(flow)
        rank = lambda e: round(self._reach.get_edge_rank(flow,e),2)
        # inferred_edges = {e : d for e : d in edges.items()
        #                   if rank(e) >= self.threshold}
        physical_edges = self._topo.links()
        # if str(flow) == "3.0.0.0/24" and source == "leaf3_0" and target == "agg0_1":
        #     print("Separating", source, "and", target)
        # print(physical_edges)
        
        ## Compute _Close_ Separator Set in physical_edges
        # get successors S of source
        successors = set([tgt for (src, tgt) in physical_edges
                          if src in sources]).union(
                                  set([tgt for tgt, src in physical_edges
                                       if src in sources]))

        if set(targets).issubset(successors):
            return []
        # print("SUCCESSORS of", source, successors)
        
        # Compute Set of Nodes R that reach target, (not including those nodes in S)
        reach = set(targets)
        separator = set()
        old_size = 0
        while len(reach) > old_size:
            old_size = len(reach)
            for (src, tgt) in physical_edges:
                if tgt in reach:
                    assert(tgt not in successors)
                    if src in successors:
                        # print("ADD-SRC", src)
                        separator.add(src)
                    else:
                        reach.add(src)
                if src in reach:
                    assert(src not in successors)
                    if tgt in successors:
                        # print("ADD-TGT", tgt)
                        separator.add(tgt)
                    else:
                        reach.add(tgt)
            # print(separator)
            size = len(reach)

        return [separator] + self.rec_separate(flow, separator, targets)
        
def mark_implied_properties(reach, topo, threshold):
    g = RestrictedGraph(reach, topo, threshold)
    for flow in reach.get_flows():
        for (s,t) in reach.get_edges(flow):
            if topo.link_exists(s,t) or \
               (threshold is not None and reach.get_edge_rank(flow, (s,t)) < threshold):
                continue
            else:
                separators = g.separate(flow, s, t) + g.separate(flow, t, s)
                used_separators = []

                # if s[:4] == "leaf" and t[:4] == "leaf":
                #     used_separators.append(set("core" + str(i) for i in range(16)))
                    
                for separator in separators:
                    # if len(separator) <= 1:
                    #     continue

                    fwd_sep = True
                    for v in separator:
                        if v[:4] == "leaf": 
                            fwd_sep = False
                            break
                        
                        rankout = reach.get_edge_rank(flow, (v,t))
                        rankin = reach.get_edge_rank(flow, (s,v))
                        rankout = -1 if rankout is None else rankout
                        rankin = -1 if rankin is None else rankin
                        if rankin <= 0:# and rankout<=0:
                            fwd_sep = False
                            break

                    if fwd_sep:
                        used_separators.append(separator)

                    
                for separator in used_separators:
                    # print(s, separator, t)                    
                    for v in separator:
                        reach.mark_edge_implied_by(flow,
                                                   premise=(s,t),
                                                   conclusion=(v,t))
                        reach.mark_edge_implied_by(flow,
                                                   premise=(s,t),
                                                conclusion=(s,v))                    

    
def main():
    parser = ArgumentParser(description="Remove Implied Properties")
    parser.add_argument("summary", help="The file path to a reachability summary")
    parser.add_argument("topo", help="The Topology file for the network from which the `summary` was collected")
    parser.add_argument("--include-implied", dest="include_implied", default=False, action="store_true",
                        help="Include the implied properties in the output")
    parser.add_argument("-t", "--threshold", default=50, type=int,
                        help="Threshold (as a percentage); ranks below the threshold are discarded; must be between 0 and 100")
    parser.add_argument("-p", "--policies-path", dest="policies_path", default=None,
                        help="List of expected policies for the `summary`")
    
    settings = parser.parse_args()
 
    # check threshold has a valid value
    if settings.threshold > 100 or settings.threshold < 0:
        print("ERROR: Value supplied to --threshold must be between 0 and 100. You supplied", settings.threshold)
        return 1
    else:
        threshold = float(settings.threshold) / 100.0


    if settings.policies_path is not None:
        # load policies
        with open(settings.policies_path, 'r') as pf:
            policies_json = pf.read()
        s_policies = parse_policies(policies_json)
    
        # Coerce path preference policies to reachability policy
        policies = []
        for idx, policy in enumerate(s_policies):
            if policy.isType(PolicyType.PATH_PREFERENCE):
                policies += [policy.toReachabilityPolicy()]
                
    reach_str = None
    with open(settings.summary) as reach_fp:
        reach_str = reach_fp.read()
        
    if reach_str is None:
        print("ERROR: Could not read from", settings.summary)
        return 1

    reach_summ = EnhancedReachSummary(reach_str, 2)
    
    topo_str = None
    with open(settings.topo) as topo_fp:
        topo_str = topo_fp.read()

    topo = Topo(topo_str)
    
    mark_implied_properties(reach_summ, topo, threshold)
    props = reach_summ.to_policy_set(show_implied=settings.include_implied, threshold=threshold)

    if settings.policies_path is None:
        for p in props:
            print(p)
    else:
        correct_policies = 0
        for p in props:
            if p in policies:
                correct_policies += 1
            # else:
            #     print("FP:", p, reach_summ.get_edge_rank(p._flow, (p._source, p._target)))
                
            
        print("Precision:", float(correct_policies/len(props)))
        print("Recall:", float(correct_policies/len(policies)))

    
if __name__ == "__main__":    
    main()
