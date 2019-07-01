#! /usr/bin/env python

from argparse import ArgumentParser
import ipaddress

arg_parser = ArgumentParser(description='Parse forwarding table')
arg_parser.add_argument('tables', nargs='+',
        help='files containing forwarding tables to parse')
arg_parser.add_argument('-o', '--output', dest='oname', action='store',
        required=True, help='path to output file')
args = arg_parser.parse_args()

wf = open(args.oname, 'w')

def parse_file(fname, AS):
    '''
    Takes in an input filename and a router AS and returns a tuple containing:
        - a dictionary mapping interfaces to their IP addresses
        - a dictionary mapping `<recursive>` interface prefix to next hop
        - a dictionary mapping prefix to interface of directly connected networks (next hop `attached`)
    '''
    interfaces = {}
    recursive = {}
    attached = {}

    rf = open(fname, 'r')

    for line in rf:

        if line[0].isdigit():
            fwd_data = line.split()
            prefix = fwd_data[0]
            next_hop = fwd_data[1]
            if len(fwd_data) > 2:
                intf = fwd_data[2]
            else:
                intf = ''

            # next hop is `receive`
            if next_hop == 'receive' and intf:
                interfaces[prefix] = intf

            # next hop is an IP address
            if next_hop[0].isdigit():
                if intf == '<recursive>':
                    recursive[prefix] = next_hop

            # next hop is `attached`
            if next_hop == 'attached':
                attached[prefix] = intf

    rf.close()
    return (interfaces, recursive, attached, AS)

# get the data from all forwarding tables
file_data = {}
AS = 1
for tbfile in args.tables:
    file_data[tbfile] = parse_file(tbfile, AS)
    AS+=1

for fwd_tb in sorted(file_data):
    # write interfaces and their IP addresses
    # write paths to which interfaces on other fwd tables
    # write all directly connected networks (which intf to which intf)

    file_intfs = file_data[fwd_tb][0]
    file_rcrs = file_data[fwd_tb][1]
    file_attch = file_data[fwd_tb][2]

    # test writing configs
    neighbor = {} # neighbor[ip] = (table, update-source)

    wf.write('----------------------------- Router: ' + fwd_tb + ' -----------------------------\n')
    # write all router interfaces and their IP addresses
    wf.write('Router Interfaces:\n')
    for i in file_intfs:
        wf.write('\tInterface ' + file_intfs[i] + ' has IP address ' + i[:-3] + '\n')

    # write all networks directly connected and to which other router interface
    # go through each attached prefix in a network and see if it is present in the other networks' keys
    for nw in file_attch:
        toWrite = True
        for tbl in sorted(file_data):
            if tbl != fwd_tb:
                if nw in file_data[tbl][2]:
                    if toWrite:
                        wf.write('\nNetwork ' + nw + ' is directly connected to:\n')
                        toWrite = False
                    wf.write('\tInterface ' + file_data[tbl][2][nw] + ' on ' + tbl + ' (via ' + file_attch[nw] + ')\n')

    # write all recursive routes that exist
    wf.write('\nRecursive Routes:\n')
    # print(fwd_tb, file_rcrs)
    for rt in file_rcrs:
        next_hop = file_rcrs[rt]
        wf.write('\tRoute ' + rt + ' to ' + file_rcrs[rt] + '\n')

        written = False
        neigh_tbl = '' # for writing configs
        for tbl in sorted(file_data):
            if tbl != fwd_tb:
                if next_hop in file_data[tbl][0]:
                    if rt in file_intfs:
                        wf.write('\t\troute from interface ' + file_intfs[rt] + ' ')
                    else:
                        wf.write('\t\troute ')
                    wf.write('to interface ' + file_data[tbl][0][next_hop] + ' on ' + tbl + '\n')
                    written = True
                    neigh_tbl = tbl
        if not written:
            wf.write('\n')

        # for writing configs
        for pfx in file_attch:
            subnet = pfx[pfx.find('/'):]
            if ipaddress.ip_network(pfx, strict=False) == ipaddress.ip_network(file_rcrs[rt][:-3] + subnet, strict=False):
                # print('neighbor added: ' + file_attch[pfx])
                neighbor[file_rcrs[rt][:-3]] = (neigh_tbl, file_attch[pfx])
        # end writing

    wf.write('\n')


    # WRITING CONFIGURATIONS
    filename = fwd_tb + '_configs'
    test = open(filename, 'w')

    # hostname
    test.write('!\nhostname %s\n' % fwd_tb)
    # configure interfaces
    for p in sorted(file_intfs):
        test.write('!\ninterface ' + file_intfs[p] + '\n')
        subnet = '/32'
        for addr in file_attch:
            if file_attch[addr] == file_intfs[p]:
                subnet = addr[addr.find('/'):]
        intf_ad = ipaddress.ip_interface('%s%s' % (p[:-3],subnet))
        test.write(' ipv4 address %s\n no shutdown\n' % (intf_ad.with_netmask.replace('/', ' ')))

    # configure router bgp, advertise originated routes
    test.write('!\nrouter bgp %s\n' % (file_data[fwd_tb][3]))
    test.write(' address-family ipv4 unicast\n')
    network_ads = []
    neigh_toWrite = []
    for n in sorted(neighbor):
        # copy neighbor's recursive routes
        neigh_rcrs = file_data[neighbor[n][0]][1].copy()
        i=0
        # if neighbor has route with you as next hop but you don't have that route
        # then you originated it
        for route in neigh_rcrs.keys():
            if route in file_rcrs:
                del neigh_rcrs[route]
            elif neigh_rcrs[route] in file_intfs:
                if route not in network_ads:
                    network_ads.append(route)
        # configure bgp neighbors
        neigh_toWrite.append(' !\n neighbor %s\n' % (n))
        neigh_toWrite.append('  remote-as %s\n' % (file_data[neighbor[n][0]][3]))
        neigh_toWrite.append('  description %s peer\n' % (neighbor[n][0]))
        neigh_toWrite.append('  update-source %s\n' % (neighbor[n][1]))

    # advertise networks
    for ad in network_ads:
        test.write('  network %s\n' % ad)

    # configure bgp neighbors
    for conf in neigh_toWrite:
        test.write(conf)
    test.write(' !\n')
    test.write('!\n')
    # END WRITING

wf.close()
