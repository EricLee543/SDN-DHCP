# original repo https://github.com/haidlir/SNHx/blob/master/dhcp.py
from ryu.lib import addrconv
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ipv4
from ryu.lib.packet import udp
from ryu.lib.packet import dhcp


class Config(object):

    controller_macAddr = '7e:49:b3:f0:f9:99' 
    start_ip = '192.168.1.2'
    end_ip = '192.168.1.100'
    netmask = '255.255.255.0'
    dns = '8.8.8.8'

    

    service = 'L2_FABRIC'
    route = {}

class DHCPServer(object):

    hw_addr = Config.controller_macAddr
    dhcp_server = {}
    netmask = '255.255.255.0'
    dns = '8.8.8.8' # any value, not important
    bin_dns = addrconv.ipv4.text_to_bin(dns)
    hostname = 'SUSTC' # any value, not important.
    bin_netmask = addrconv.ipv4.text_to_bin(netmask)
    segment = 0
    wan_pool = {}
    wan_leases = {}
    wan_offers = {}
    lease_time = 60 * 60

    @classmethod
    def get_option_value(cls, dhcp_pkt, tag):
        for option in dhcp_pkt.options.option_list:
            if option.tag == tag:
                if option.tag == 50:
                    return addrconv.ipv4.bin_to_text(option.value)


    @classmethod
    def assemble_ack(cls, pkt, datapath, port):
        req_eth = pkt.get_protocol(ethernet.ethernet)
        req_ipv4 = pkt.get_protocol(ipv4.ipv4)
        req_udp = pkt.get_protocol(udp.udp)
        req = pkt.get_protocol(dhcp.dhcp)

        wanted_ip = cls.get_option_value(req, 50)
        src = req_eth.src
        got_ip = None
        if src in cls.wan_leases[datapath]:
            if wanted_ip != cls.wan_leases[datapath][src]:
                cls.wan_pool.append(cls.wan_leases[datapath][src])
                del cls.wan_leases[datapath][src]
            else:
                got_ip = cls.wan_leases[datapath][src]
        if got_ip is None:
            if src in cls.wan_offers[datapath]:
                if wanted_ip != cls.wan_offers[datapath][src]:
                    cls.wan_pool.append(cls.wan_offers[datapath][src])
                    del cls.wan_offers[datapath][src]
                else:
                    got_ip = cls.wan_offers[datapath][src]
        if got_ip is None:
            if wanted_ip in cls.wan_pool[datapath]:
                cls.wan_pool[datapath].remove(wanted_ip)
                got_ip = wanted_ip
        if got_ip is None:
            # cls.log.warn("%s asked for un-offered %s", src, wanted_ip)
            # cls.nak(event) # nak 
            return

        req.options.option_list.remove(next(opt for opt in req.options.option_list if opt.tag == 53))
        req.options.option_list.insert(0, dhcp.option(tag=1, value=cls.bin_netmask))
        req.options.option_list.insert(0, dhcp.option(tag=3, value=addrconv.ipv4.text_to_bin(cls.dhcp_server[datapath])))
        req.options.option_list.insert(0, dhcp.option(tag=6, value=cls.bin_dns))
        req.options.option_list.insert(0, dhcp.option(tag=51, value=b'\x00\x00\x21\xc0'))
        req.options.option_list.insert(0, dhcp.option(tag=53, value=b'\x05'))
        req.options.option_list.insert(0, dhcp.option(tag=54, value=addrconv.ipv4.text_to_bin(cls.dhcp_server[datapath])))

        ack_pkt = packet.Packet()
        ack_pkt.add_protocol(ethernet.ethernet(ethertype=req_eth.ethertype, dst=src, src=cls.hw_addr))
        ack_pkt.add_protocol(ipv4.ipv4(dst=req_ipv4.dst, src=cls.dhcp_server[datapath], proto=req_ipv4.proto))
        ack_pkt.add_protocol(udp.udp(src_port=67,dst_port=68))
        ack_pkt.add_protocol(dhcp.dhcp(op=2, chaddr=src,
                                       hlen=6, # salah di len
                                       siaddr=cls.dhcp_server[datapath],
                                       boot_file=req.boot_file,
                                       yiaddr=wanted_ip,
                                       xid=req.xid,
                                       options=req.options))
        # cls.logger.info("ASSEMBLED ACK: %s" % ack_pkt)


        # print(wanted_ip, src, datapath, port)
        return ack_pkt

    @classmethod
    def assemble_offer(cls, pkt, datapath):
        disc_eth = pkt.get_protocol(ethernet.ethernet)
        disc_ipv4 = pkt.get_protocol(ipv4.ipv4)
        disc_udp = pkt.get_protocol(udp.udp)
        disc = pkt.get_protocol(dhcp.dhcp)

        src = disc_eth.src 
        if src in cls.wan_leases[datapath]:
            offer = cls.wan_leases[datapath][src]
            del cls.wan_leases[datapath][src]
            cls.wan_offers[datapath][src] = offer
        else:
            offer = cls.wan_offers[datapath].get(src)
            if offer is None:
                if len(cls.wan_pool[datapath]) == 0:
                    # cls.logger.error("Out of IP addresses")
                    # dhcp nak belum dibuat
                    # cls.nak(pkt)
                    return

                offer = cls.wan_pool[datapath][0]
                # jika request IP diminta belum dibuat
                cls.wan_pool[datapath].remove(offer)
                cls.wan_offers[datapath][src] = offer

        yiaddr = offer
        disc.options.option_list.remove(next(opt for opt in disc.options.option_list if opt.tag == 55))
        disc.options.option_list.remove(next(opt for opt in disc.options.option_list if opt.tag == 53))
        disc.options.option_list.remove(next(opt for opt in disc.options.option_list if opt.tag == 12))
        disc.options.option_list.insert(0, dhcp.option(tag=1, value=cls.bin_netmask))
        disc.options.option_list.insert(0, dhcp.option(tag=3, value=addrconv.ipv4.text_to_bin(cls.dhcp_server[datapath])))
        disc.options.option_list.insert(0, dhcp.option(tag=6, value=cls.bin_dns))
        # disc.options.option_list.insert(0, dhcp.option(tag=12, value=cls.hostname))
        disc.options.option_list.insert(0, dhcp.option(tag=53, value=b'\x02'))
        disc.options.option_list.insert(0, dhcp.option(tag=54, value=addrconv.ipv4.text_to_bin(cls.dhcp_server[datapath])))

        offer_pkt = packet.Packet()
        offer_pkt.add_protocol(ethernet.ethernet(ethertype=disc_eth.ethertype, dst=src, src=cls.hw_addr))
        offer_pkt.add_protocol(ipv4.ipv4(dst=disc_ipv4.dst, src=cls.dhcp_server[datapath], proto=disc_ipv4.proto))
        offer_pkt.add_protocol(udp.udp(src_port=67,dst_port=68))
        offer_pkt.add_protocol(dhcp.dhcp(op=2, chaddr=src,
                                         hlen=6, # salah di len
                                         siaddr=cls.dhcp_server[datapath],
                                         boot_file=disc.boot_file,
                                         yiaddr=yiaddr,
                                         xid=disc.xid,
                                         options=disc.options))
        return offer_pkt

    @classmethod
    def get_state(cls, pkt_dhcp):
        dhcp_state = ord([opt for opt in pkt_dhcp.options.option_list if opt.tag == 53][0].value)
        if dhcp_state == 1:
            state = 'DHCPDISCOVER'
        elif dhcp_state == 2:
            state = 'DHCPOFFER'
        elif dhcp_state == 3:
            state = 'DHCPREQUEST'
        elif dhcp_state == 5:
            state = 'DHCPACK'
        return state

    # must be implemented
    @classmethod
    def handle_dhcp(cls, datapath, port, pkt):

        def _l2_fabric_dhcp():
            # not use the config because there is no time to change netmask/ subnet size.
            # In student's project, this part should be configured by Config class which determines 
            # the size of subnet and other parameters.
            if cls.segment == 0:
                cls.big_pool = ['192.168.1.' + str(x) for x in range(2,255)]
                cls.big_pool += ['192.168.1.' + str(x) for x in range(1,254)]
                cls.netmask = '255.255.255.0'
                cls.bin_netmask = addrconv.ipv4.text_to_bin(cls.netmask)
                cls.segment = 1
            if datapath not in cls.wan_pool:
                cls.dhcp_server[datapath] = '192.168.1.1'
                cls.wan_pool[datapath] = cls.big_pool
                cls.wan_offers[datapath] = {}
                cls.wan_leases[datapath] = {}

        _l2_fabric_dhcp()

        pkt_dhcp = pkt.get_protocols(dhcp.dhcp)[0]
        dhcp_state = cls.get_state(pkt_dhcp)
        if dhcp_state == 'DHCPDISCOVER':
            cls._send_packet(datapath, port, cls.assemble_offer(pkt, datapath))
        elif dhcp_state == 'DHCPREQUEST':
            cls._send_packet(datapath, port, cls.assemble_ack(pkt, datapath, port))
        else:
            return

    @classmethod
    def _send_packet(cls, datapath, port, pkt):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        if isinstance(pkt, str):
            pkt = pkt.encode()
        pkt.serialize()
        data = pkt.data
        actions = [parser.OFPActionOutput(port=port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                  buffer_id=ofproto.OFP_NO_BUFFER,
                                  in_port=ofproto.OFPP_CONTROLLER,
                                  actions=actions,
                                  data=data)
        datapath.send_msg(out)