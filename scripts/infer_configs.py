#! /usr/bin/python3

from argparse import ArgumentParser
import sys
import json
import nopticon
import os
import pygraphviz
import ipaddress

def parse_topo(topo):
    '''
    Takes in a topo file
    Returns a dictionary containing all routers in the network,
    each with a dictionary with keys:
        - 'AS': the AS number assigned to this router
        - 'interfaces': a dictionary that contains their interfaces and IP addresses
            * dict[intf] = ip address
        - 'physical_links': a dictionary containing neighbors and the names of their connected interfaces
            * dict[neighbor] = (connected intf on this router, connected intf on neighbor)
        - 'neighbors': a list of neighboring routers
        - 'orig_routes': a list of routes this router originated
        - 'filtered': a dictionary containing filtered flows
            * dict[flow] = [ neighbors advertising flow to this router ]
        - 'learned': a dictionary containing the flow and which neighbors it was learned from
            * dict[flow] = [ neighbors advertising flow to this router ]
    '''
    routers = {}
    AS = 1
    for line in topo:
        ln = line.split()
        if ln[0] == 'router':
            # line indicates interfaces
            if ln[1] not in routers:
                routers[ln[1]] = {}
                routers[ln[1]]['AS'] = AS
                AS += 1
                routers[ln[1]]['interfaces'] = {}
                routers[ln[1]]['physical_links'] = {}
                routers[ln[1]]['neighbors'] = []
                routers[ln[1]]['orig_routes'] = []
                routers[ln[1]]['filtered'] = {}
                routers[ln[1]]['learned'] = {} # flow: neighbor(s) learned from

            # add interfaces and their IPs to router dictionary
            for i in range(len(ln)-2):
                i+=2
                (intf, ip) = ln[i].split(':')
                routers[ln[1]]['interfaces'][intf] = ip

        elif ln[0] == 'link':
            # line indicates a link between two devices
            assert(len(ln) == 3) # must have a link and two devices
            # find the router and its associated interface
            (r1, int1) = ln[1].split(':')
            (r2, int2) = ln[2].split(':')

            routers[r1]['physical_links'][r2] = (int1, int2)
            routers[r2]['physical_links'][r1] = (int2, int1)

    return routers


def flow_graph(flow, links, timestamp):
    '''
    Make flow-specific graph
    '''
    # Create graph
    graph = pygraphviz.AGraph(strict=False, directed=True)

    for source, targets in links.items():
        for target in targets:
            graph.add_edge(source, target)
    return graph

def parse_graphs(routers, link_summary, route_origins, timestamp='end'):
    '''
    Update `routers` with originated routes and neighbors from each graph
    '''
    for flow in link_summary.get_flows():
        graph = flow_graph(flow, link_summary.get_links(flow), timestamp)
        originated(graph, flow, routers, route_origins)
        neighbors(graph, routers)


def originated(graph, flow, routers, route_origins):
    '''
    Find originated routes from per-flow network graphs
    Add originated routes to the router dictionary
    '''
    # routes are an IPv4Network object
    for node,degree in graph.out_degree_iter():
        # if out degree for a node is 0, that flow was originated by the node
        if degree == 0 and graph.in_degree(with_labels=True)[node] >= 1:
            routers[node]['orig_routes'].append(flow)
            route_origins[flow] = node

def neighbors(graph, routers):
    '''
    Find neighbors for each router in the topology
    '''
    for n in graph.iternodes():
        for nbr in graph.iterneighbors(n):
            if nbr not in routers[n]['neighbors']:
                routers[n]['neighbors'].append(nbr)


def reach_graph(flow, edges, timestamp):
    graph = pygraphviz.AGraph(strict=False, directed=True)
    for source, target in edges.keys():
        graph.add_edge(source, target)
    return graph

def reachability(routers, reach_summary, timestamp='end'):
    '''
    Update `routers` with reachability information:
        - filtered routes from each graph
        - where routes were learned from
    '''
    for flow in reach_summary.get_flows():
        graph = reach_graph(flow, reach_summary.get_edges(flow), timestamp)
        filters(graph, flow, routers)
        learned_routes(graph, flow, routers)


def learned_routes(graph, flow, routers):
    '''
    Updates routers with where that router learned routes
    dict[flow] = [ list of neighbors advertising that flow to you ]
    '''
    for n in graph.iternodes():
        for nbr in graph.iterneighbors(n):
            if graph.out_degree(nbr) >= 1:
                if flow not in routers[n]['learned']:
                    routers[n]['learned'][flow] = []
                if nbr in routers[n]['neighbors'] and nbr not in routers[n]['learned'][flow]:
                    routers[n]['learned'][flow].append(nbr)


def filters(graph, flow, routers):
    '''
    If there is no edge in the end summary from you to a neighbor, assume there is a filter
    Modifies router dictionary to include filters
        * routers[router]['filtered'][flow] = [ neighbors advertising flow to this router ]
    '''
    # TODO: need a destination in filter parsing ?
    for node,degree in graph.out_degree_iter():
        # if out degree is greater than one, advertising that flow
        if degree >= 1:
            for nbr in routers[node]['neighbors']:
                # if no edge from you to neighbor, that flow is filtered
                if not graph.has_edge(node, nbr):
                    if not graph.has_edge(nbr, node):
                        print(nbr, node)
                        print(graph)
                        if flow not in routers[nbr]['filtered']:
                            routers[nbr]['filtered'][flow] = []
                        routers[nbr]['filtered'][flow].append(node)
    # for rtr in routers:
    #     no_edge = routers[rtr]['neighbors'][:]
    #     for flow in end_sum['reach-summary']:
    #         for edge in flow['edges']:
    #             if edge['target'] in no_edge:
    #                 no_edge.remove(edge['target'])
    #     routers[rtr]['filtered'] = no_edge


# def filter_rules(routers, route_origins):
#     rules = {}
#     # dict[router] = {filtered route: rule, ...}
#     for r in routers:
#         rules[r] = {}
#         filt = routers[r]['filtered']
#         for flow in filt:
#             if filt != []:
#                 rules[r][flow] = filter_rule(routers, r, flow, route_origins)
#
#     return rules

def filter_rule(routers, router, flow, route_origins):
    '''
    Determine the filtering rule (prefix, neighbor, origin...)
    '''
    # True until proven False ?
    neighbor = True
    origin = True

    # prefix
    # try to longest prefix match with varying subnet masks?
    # filtered flows have destination node stored in dictionary
    # how to find prefix-set?
    # destination - if other routes to same destination, unlikely to be cause

    # if learned a route from same neighbor as filtered neighbors, unlikely to be cause
    filt_nbrs = routers[router]['filtered'][flow]
    for nbr in filt_nbrs:
        for rt in routers[router]['learned']:
            if nbr in routers[router]['learned'][rt]:
                neighbor = False
                break

    # if learned a route from same origin as filtered origin, unlikely to be cause
    origin = route_origins[flow]
    for rt in route_origins:
        if route_origins[rt] == origin and rt in routers[router]['learned']:
            origin = False
            break

    if not origin and not neighbor:
        # TODO: add support for prefix filter
        # ipaddress.ip_network(prefix, strict=False)
        rule = ['prefix']
    if origin and not neighbor:
        rule = ['origin', origin]
    if not origin and neighbor:
        rule = ['neighbor']
    return rule


def configs(configs_path, routers, route_origins):
    for r in routers:
        file = open(configs_path + r + '_configs', 'w')
        generate_config(file, routers, r, route_origins)
        file.close()

def generate_config(file, routers, rtr, route_origins):
    '''
    Write configurations from learned information
    For now, assign different AS to each router automatically
    '''
    file.write('!\nhostname %s\n' % rtr)
    # configure interfaces
    # TODO: change interface names to correct format
    for i in sorted(routers[rtr]['interfaces']):
        if i[:-1] == 'gi':
            interface = 'GigabitEthernet0/0/0/' + i[-1]
        elif i[:-1] == 'MgmtEth':
            interface = 'MgmtEth0/RP0/CPU0/0'
        else:
            interface = i
        file.write('!\ninterface ' + interface + '\n')
        file.write(' ipv4 address %s\n no shutdown\n' % (routers[rtr]['interfaces'][i]))

    # configure static routes
    static_routes = []
    for rt in routers[rtr]['orig_routes']:
        static_routes.append(rt)
        for i in routers[rtr]['interfaces']:
            if rt == ipaddress.ip_network(routers[rtr]['interfaces'][i], strict=False):
                static_routes.remove(rt)
                break
    if static_routes != []:
        file.write('!\nrouter static\n address-family ipv4 unicast\n')
        for st in static_routes:
            # all Null0 for now
            file.write('  %s Null0\n' % str(st))
        file.write(' !\n')

    file.write('!\nroute-policy accept\n pass\nend-policy\n')

    # TODO: adapt for other route policies
    route_policy_origin = []
    for f in routers[rtr]['filtered']:
        if routers[rtr]['filtered'][f] != []:
            rule = filter_rule(routers, rtr, f, route_origins)
            if rule[0] == 'origin' and rule[1] not in route_policy_origin:
                route_policy_origin.append(rule[1])
    if route_policy_origin != []:
        policy_name = 'no'
        if_statement = ' if '
        for node in route_policy_origin:
            if if_statement != ' if ':
                if_statement += ' or '
            policy_name += '-' + node
            if_statement += "as-path originates-from '" + str(routers[node]['AS']) + "'"
        if_statement += ' then \n  drop\n else\n  pass\n endif\nend-policy'
        policy_name += '-import'
        file.write('!\nroute-policy %s\n%s\n' % (policy_name, if_statement))
    else:
        policy_name = 'accept'

    # configure bgp
    file.write('!\nrouter bgp %s\n address-family ipv4 unicast\n' % (routers[rtr]['AS']))
    # advertised networks
    for orig in routers[rtr]['orig_routes']:
        file.write('  network %s\n' % (orig))
    # configure neighbors
    for n in routers[rtr]['neighbors']:
        (update_src, nbr_int) = routers[rtr]['physical_links'][n]
        if update_src[:-1] == 'gi':
            update_src = 'GigabitEthernet0/0/0/' + update_src[-1]
        elif update_src[:-1] == 'MgmtEth':
            update_src = 'MgmtEth0/RP0/CPU0/0'
        nbr_int = routers[n]['interfaces'][nbr_int]
        file.write(' !\n neighbor %s\n' % (nbr_int[:nbr_int.find('/')]))
        file.write('  remote-as %s\n' % (routers[n]['AS']))
        file.write('  description %s peer\n' % (n))
        file.write('  update-source %s\n' % (update_src))
        file.write('  address-family ipv4 unicast\n')
        # only works for origin right now
        # TODO: adapt for export policies
        file.write('   route-policy %s in\n   route-policy accept out\n  !\n' % (policy_name))
    file.write(' !\n!\n')

    file.close()


def main():
    arg_parser = ArgumentParser(description='Parse end_summary.json')
    arg_parser.add_argument('-s', '--summary', dest='end_sum', action='store',
            required=True, help='path to end_summary.json file')
    arg_parser.add_argument('-t', '--topo', dest='topo', action='store',
            required=True, help='path to topo file')
    arg_parser.add_argument('-o', '--output_file', dest='output', action='store',
            help='path to output file, generates lists of router attributes')
    arg_parser.add_argument('-cp', '--configs_path', dest='configs_path', action='store',
            help='provide a path to the desired directory if you want to generage configurations')
    args = arg_parser.parse_args()

    if args.end_sum == args.output:
        sys.exit()

    with open(args.end_sum, 'r') as f:
        end_sum = json.load(f)
    f.close()

    sf = open(args.end_sum, 'r')

    topo = open(args.topo, 'r')
    if args.output:
        output = open(args.output, 'w+')
    else:
        output = sys.stdout

    routers = parse_topo(topo)
    topo.close()
    route_origins = {}

    for i, summary_json in enumerate(sf):
        link_summary = nopticon.LinkSummary(summary_json)
        parse_graphs(routers, link_summary, route_origins, '%010d' % (i))

        reach_summary = nopticon.ReachSummary(summary_json)
        reachability(routers, reach_summary, '%010d' % (i))
    sf.close()

    # filters = filter_rules(routers, route_origins)

    for rtr in sorted(routers):
        output.write('======== ROUTER %s ========\n' % (rtr))
        output.write('INTERFACES:\n')
        for intf in routers[rtr]['interfaces']:
            output.write('\tInterface %s: %s\n' % (intf, routers[rtr]['interfaces'][intf]))
        output.write('\nORIGINATED ROUTES:\n')
        for route in routers[rtr]['orig_routes']:
            output.write('\t%s\n' % (str(route)))
        output.write('\nNEIGHBORS:\n')
        for nbr in routers[rtr]['neighbors']:
            output.write('\t%s\n' % (nbr))

        output.write('\nFILTERED:\n')
        for f in routers[rtr]['filtered']:
            if routers[rtr]['filtered'][f] != []:
                output.write('\tFlow %s to neighbor(s) %s\n' % (f, sorted(routers[rtr]['filtered'][f])))
                output.write('\t\tFiltered by %s\n' % (str(filter_rule(routers, rtr, f, route_origins))))

        output.write('\n\n')

    if args.output:
        output.close()

    if args.configs_path:
        configs(args.configs_path, routers, route_origins)

if __name__ == "__main__":
    main()
