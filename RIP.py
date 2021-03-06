import sys
import socket
import select
import json
import time
import threading
import random


#information from configure file,
my_router_id = None
input_ports =[]
#the elements in the following two arraies correspond to each other,
#which means output_ports[index] belongs neighbours[index] 
output_ports = []
neighbours = []


"""Each router that implements RIP is assumed to have a routing table.
This table has one entry for every destination that is reachable
throughout the system operating RIP. Each entry contains at least
the following information:
- The IPv4 address of the destination.
- A metric, which represents the total cost of getting a datagram
from the router to that destination. This metric is the sum of the
costs associated with the networks that would be traversed to get
to the destination.
- The IPv4 address of the next router along the path to the
destination (i.e., the next hop). If the destination is on one of
the directly-connected networks, this item is not needed.
- A flag to indicate that information about the route has changed
recently. This will be referred to as the "route change flag."
- Various timers associated with the route. See section 3.6 for more
details on timers."""
configure_table = []


# listen socket list
listen_sockets = []

#routing table
routing_table = []


#routing table config data
MAX_METRIC = 16
HEAD_ERCOMMAND = 2
HEAD_VERSION = 2
MUST_BE_ZERO = 0
ADDRESS_FAMILY_IDENTIFIER = 2

#default timer setting for presentation we redefine them to short the waiting time
TIME_OUT = 20 #default 180
GARBAGE_COLLECT_TIME = 20 #default 120
PERIODIC_TIME = 10 #default 30
CHECK_TIME = 4 # after a triggered update is sent, a timer should be set 
#for a random interval between 1 and 5, so we choose 4

#timers
periodic_timer = None
timeout_timer = None
garbage_collection_timer = None





#######################   read configure file         ##########################
"""configure file format:
router-id 1
input-ports 6110,6210,7345
outputs 5002-2-1,5003-6-5,5004-7-8
"""
def loadConfigFile(fileName):
    #using the global keyworld means we need to change it in this function
    global my_router_id, input_ports ,output_ports ,configure_table ,listen_pockets 
    file = open(fileName)
    lines = file.read().splitlines()
    for line in lines:
        data = line.split(' ')
        if data[0] == 'router-id':# read the first line
            if isValidId(int(data[1])):#vertify validity
                my_router_id = int(data[1])
            else:
                print('Invalid Id Number')
                exit(0)
        elif data[0] == 'input-ports':#second line
            ports = data[1].split(',')
            for port in ports:
                if isValidPort(int(port)): #vertify validity
                    input_ports.append(int(port))# add to list
                else:
                    print('Invalid Id Number in input-ports')
                    exit(0)
        elif data[0] == 'outputs':
            items = data[1].split(',')
            for item in items:
                ports = item.split('-')
                if (isValidPort(int(ports[0])) and isValidId(int(ports[1]))):
                    table_item = {
                        "destination": int(ports[1]),
                        "metric": int(ports[2]), 
                        "next_hop_id": int(ports[1]),
                        "router_change_flag" : False,
                        "garbage_collect_start": None,
                        "last_update_time": None
                    } # one sigle information int table format 
                    configure_table.append(table_item) #add to configure table
                    output_ports.append(ports[0]) # 
                    neighbours.append(ports[1])
                else:
                    print('Invalid Id Number or RouterId in outputs')
                    exit(0)                    
        else:         
            print('Invalid configure file')
            exit(0)
    file.close()
    print('log file succeed')
    print('inports number are {0}'.format(input_ports)) 
    print('outports number are {0}'.format(output_ports))
    print('directly neighbours are {0}'.format(output_ports))
    print('>>>>>>>>>>>>RIP routing table:' + str(my_router_id)) 
    printTable()      


  
    

"""check the port is or not between 1024 and 64000"""
def isValidPort(port):
    if port >=1024 and port <=64000:
        return True
    else:
        return False
"""check the router Id is or not between 1 and 64000"""
def isValidId(num):
    if num>=1 and num <= 64000:
        return True
    else:
        return False


##################### create listen sockets to each neighbor###################   
def initListenSocket():
    """traverse input_ports array and create socket for each port then store
    it in listen_sockets array"""
    global listen_sockets
    try:
        for port in input_ports: 
            inSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            inSocket.bind(('', int(port)))
            listen_sockets.append(inSocket)
            print('creat listen socket:{} succeed'.format(port))
    except Exception as err:
        print('creat listen socket error:{0}'.format(err))


####################         set timers to response        ##################### 
def initPeriodicTimer():
    """Every 30 seconds in our doc is PERIODIC_TIME = 10, the RIP process is awakened to send an unsolicited
Response message containing the complete routing tableto every neighboring router."""
    global periodic_timer
    #seting a periodic_timer which can excute sendUnsoclicitedResponse function when the time is up
    periodic_timer = threading.Timer(PERIODIC_TIME, sendUnsoclicitedResponse, [])
    periodic_timer.start() #start this timer
    
    
def initTimeoutTimer():
    global timeout_timer
    #as we metioned before, after send triggered update is sent, time will be set for 4.
    timeout_timer = threading.Timer(CHECK_TIME, processRouteTimeout, [])
    timeout_timer.start()
    
def initGarbageCollectionTimer():
    global garbage_collection_timer
    #as we metioned before, after send triggered update is sent, time will be set for 4.    
    garbage_collection_timer = threading.Timer(CHECK_TIME, processGarbageCollection, [])
    garbage_collection_timer.start()


def sendUnsoclicitedResponse():
    """an unsolicited Response message containing the complete routing table"""
    global periodic_timer
    sendPacket(False)  #send out the whole routing table
    
    #The 30-second timer is offset by a small random time (+/- 0 to 5 seconds) each time it is set.    
    random_offset = random.randint(-5,5)
    period = PERIODIC_TIME + random_offset
    periodic_timer.cancel()
    periodic_timer = threading.Timer(period, sendUnsoclicitedResponse, [])
    periodic_timer.start()


def processRouteTimeout():
    """If 180 seconds elapse from the last time the timeout was initialized, the route is
considered to have expired, Upon expiration of the timeout, the route
is no longer valid; however, it is retained in the routing table for
a short time so that neighbors can be notified that the route has been dropped"""
    global timeout_timer
    for item in routing_table:
        destination = item['destination']
        if destination != my_router_id:
            # if the destination information is not been updated or the time is unexpired
            #pass and wait next started time to process
            if item['last_update_time'] is None or (time.time()- item['last_update_time']) < TIME_OUT:
                pass
            else:
                print("{0} is detected to time out, update table".format(destination))
                # when update table need to set the router_change_flag to True, means it was changed, and trigger an update
                updateRoutingTable(destination, MAX_METRIC, item['next_hop_id'],True)
                
   #The 30-second timer is offset by a small random time (+/- 0 to 5 seconds) each time it is set.             
    random_offset = random.randint(-5,5)
    period = TIME_OUT + random_offset
    timeout_timer.cancel()
    timeout_timer = threading.Timer(period, processRouteTimeout, [])
    timeout_timer.start()        


def processGarbageCollection():
    """Upon expiration of the garbage-collection timer, the
route is finally removed from the routing table"""
    global garbage_collection_timer
    for item in routing_table:
        destination = item['destination']
        if destination != my_router_id:
            # if the destination information is not been updated or the time is unexpired
            #pass and wait next started time to process
            if item['garbage_collect_start'] is None or (time.time() - item['garbage_collect_start']) < GARBAGE_COLLECT_TIME:
                pass
            else:
                # when the garbage collect time is expired, delete from table
                deleteFromTable(destination)
     #The 30-second timer is offset by a small random time (+/- 0 to 5 seconds) each time it is set.                              
    random_offset = random.randint(-5,5)
    period = GARBAGE_COLLECT_TIME + random_offset
    garbage_collection_timer.cancel()
    garbage_collection_timer = threading.Timer(period, processGarbageCollection, [])
    garbage_collection_timer.start()     



#################################  create the response packet###############


def createPacket(index, isUpdateOnly):
    """use to compose package when isUpdateOnly is true means this packet is used
    for update message by trigger""" 
    
    body = []   
    neighbourId = neighbours[index]
    package = {} 
    package['header'] = createPacketHeader()
   
    for item in routing_table:
        if isUpdateOnly:# only package the router_change_flag= true information
                #the flag is not changed, do not put this message to package
            if item['router_change_flag'] == 'False':
                continue
                
            #poisoned reverse: set the metric of router which learn from this neighbour to 16
        if item['next_hop_id'] ==  neighbourId and item['destination'] != neighbourId:
            entry = createPacketEntry(item['destination'], 16)
        else:
            entry = createPacketEntry(item['destination'], item['metric'])    
        body.append(entry)
    package['entry'] = body
        
    return package          

def createPacketHeader():
    """create packet header header format: command|version|must be zero|id"""
    header = [HEAD_ERCOMMAND,HEAD_VERSION,MUST_BE_ZERO,int(my_router_id)]
    return header

def createPacketEntry(destination,metric):
    """create packet entry, format: address family identifier|must be zero| IPv4 address
    |must be zero|must be zero|metric"""  
    entry = [ADDRESS_FAMILY_IDENTIFIER,MUST_BE_ZERO,destination,
             MUST_BE_ZERO,MUST_BE_ZERO,metric]
    return entry
    
    
    

#######################send RIP response            ############################
def sendPacket(isUpdateOnly):
    """send package to each neighbour when isUpdateOnly= true means it needs to send only updated table message"""
    try:   
        #listen to all of sckets simultaneously.
        rs, ws, es = select.select([],listen_sockets,[])
        #get the sockets we can send message
        sendSocket = ws[0]
        
        for i in range(0,len(output_ports)):
            packet = createPacket(i,isUpdateOnly)
            #print(packet)
            #convert python object into json string and encode 
            message = json.dumps(packet).encode('utf-8')
            sendSocket.sendto(message,('', int(output_ports[i])))
            
                        
        """once all of the triggered updates have been generated
        the router change falgs shoule be cleared"""
        if(isUpdateOnly):
            print("send trigger message  succeed")
            for item in routing_table:
                item['router_change_flag'] = False  
        else:
            print("send unsolicited message  succeed")   
            
    except Exception as err:
        print('sendpackage error:{0}'.format(err))
        
def sendDeleteTriggerPacket(destination):
    """only using for trigger update messaget which need to delete an item """
    try:   
        #listen to all of sockets simultaneously
        rs, ws, es = select.select([],listen_sockets,[])
         #get the sockets we can send message
        sendSocket = ws[0]
        
        for i in range(0,len(output_ports)):
            packet = {} 
            entry = []
            packet['header'] = createPacketHeader()            
            entry.append(createPacketEntry(destination, MAX_METRIC) )
            packet['entry'] = entry
            #print(packet)
            #convert python object into json string and encode 
            message = json.dumps(packet).encode('utf-8')
            sendSocket.sendto(message,('', int(output_ports[i])))
                 
        print("send trigger message  succeed")
             
    except Exception as err:
        print('sendpackage error:{0}'.format(err))    

        
               
############################### receive packets from sockets         ###########        
def recvPacket():
    '''after the listenSocket the recv threads is receiving data from the socket 
    which connect this socket.'''
    
    while True:
        rs, ws, es = select.select(listen_sockets,[],[])
        for r in rs:#traverse the readable socket
            if r in listen_sockets:
                message, address = r.recvfrom(2048)
                #decode and convert json string into python object 
                packet = json.loads(message.decode('utf-8'))
                print("message received: {0}".format(packet))
                if IsValidPacket(packet): #check the packet is or not legal  
                    processPacket(packet)
                else:
                    print("Invalid packet.")
                
 
def IsValidPacket(packet):
    """
    The basic validation tests are:
    - is the destination address valid (e.g., unicast; not net 0 or 127)
    - is the metric valid (i.e., between 1 and 16, inclusive)
    If any check fails, ignore that entry and proceed to the next.
    
    vertify  validity check the version match 2
    and the routerid and ports are valubable   
    header format:command|version|must be zero|id 
    entry format: address family identifier|must be zero| IPv4 address
    |must be zero|must be zero|metric"""   
    isValid = True
    tempRouterid = packet['header'][3]
    if packet['header'][0] != HEAD_ERCOMMAND or packet['header'][1] != HEAD_VERSION :
        isValid =False
    if packet['header'][2] != MUST_BE_ZERO or isValidId(tempRouterid)==False:
        isValid =False
    if 'entry'in packet.keys():
        entry = packet['entry']
        for item in entry:
            routerId = item[2]
            if isValidId(routerId)==False or ( item[5]>16 or item[5] <0):
                isValid =False
    return isValid
 
########################process       packet             #######################
def processPacket(packet):
    """Once the entry has been validated, update the metric by adding the
cost of the network on which the message arrived. If the result is
greater than infinity, use infinity. That is,
metric = MIN (metric + cost, infinity)......see P27 in <<rfc2453-rpv2.pdf>>"""
    sendRouterId = packet['header'][3]
    
    #get the sender infomation from routing table 
    senderInfo = getItemFromRoutingTable(sendRouterId)  
    senderConfigerInfo = getItemFromConfigerTable(sendRouterId)
    #this sender is not exit, get infotmation from configure table which read from configure file
    #then add into routing table, else check the meric is or not change 
    if senderInfo is None:
        addToRoutingTable(sendRouterId,senderConfigerInfo['metric'], sendRouterId)
    else:
        if int(senderInfo['metric']) < int(senderConfigerInfo['metric']):
            updateRoutingTable(sendRouterId,senderInfo['metric'],sendRouterId, True)
        else:
            updateRoutingTable(sendRouterId,senderInfo['metric'],sendRouterId, False)
        
    #deal with entry informatin
    if 'entry' in packet.keys():
        entry = packet['entry']
        for item in entry:
            destination = item[2]
            if destination == my_router_id:# it 
                continue
            metric = item[5]
            totalMetric = metric + senderConfigerInfo['metric']
            if totalMetric >= MAX_METRIC:
                totalMetric = MAX_METRIC            
        #get the new destination information from touring table
            destItemInfo = getItemFromRoutingTable(destination) 
             
        #if not in the table, check the metric then add to routing table 
            if  destItemInfo is None:
                if totalMetric < MAX_METRIC:
                    addToRoutingTable(destination,totalMetric, sendRouterId)  
        #if exist, compare the next hop is the sender or can connect directly.
            else:  
                #destination learn from sender
                if destItemInfo['next_hop_id'] == sendRouterId: # sender connect directly 
                    if int(destItemInfo['metric'])!= totalMetric:
                        updateRoutingTable(destination,totalMetric,sendRouterId,True)
                    else:
                        updateRoutingTable(destination,totalMetric,sendRouterId,False)
                        
                #destination which sender learn from myself and poisioned reverse by sender        
                if destItemInfo['next_hop_id'] in neighbours: # sender connect directly 
                    pass
                else: #the next hop is not the sender
                    if int(destItemInfo['metric'])<= totalMetric :
                        pass
                    else:
                        updateRoutingTable(destination,totalMetric,sendRouterId,True)


################################operate routing table            ###############
def deleteFromTable(destination):
    """when delete an item in the dictionary need to find the index frist then remove the index"""
    for item in  routing_table:
        if item['destination'] == destination:
            routing_table.remove(item)
    sendDeleteTriggerPacket(destination)
    print(">>>>>>>>>>>>>>>>delete one from table")
    printTable()

def getItemFromConfigerTable(routerId):
    table_item = None
    for item in configure_table:
        if item['destination'] == routerId:
            return item
        
    return None    

def getItemFromRoutingTable(routerId):
    table_item = None
    for item in routing_table:
        if item['destination'] == routerId:
            return item
    return None


def addToRoutingTable(destination, metric, nextHop):
    """Adding a route to the routing
table consists of:
- Setting the destination address to the destination address in the RTE
- Setting the metric to the newly calculated metric (as described above)
- Set the next hop address to be the address of the router from which the datagram came
- Initialize the timeout for the route. If the garbage-collection
timer is running for this route, stop it 
- Set the route change flag
- Signal the output process to trigger an update (see section 3.8.1"""
    table_item = {
                    "destination": destination,
                    "metric": metric, 
                    "next_hop_id": nextHop,
                    "router_change_flag" : True,
                    "garbage_collect_start": None,
                    "last_update_time": time.time()
                }   
    routing_table.append(table_item)
    #trigger an update
    sendPacket(True)
    print(">>>>>>>>>>>>>>>>add to routing table")
    printTable()

def getIndexFromTable(destination):
    for i in range(0, len(routing_table)):
        if routing_table[i]['destination'] ==  destination:
            return i
    return -1


def updateRoutingTable(destination, metric, nextHop, routeChange):
    """If the new metric is the same as the old one, it is simplest to do
nothing further (beyond re-initializing the timeout, as specified
above); but, there is a heuristic which could be applied. Normally,
it is senseless to replace a route if the new route has the same
metric as the existing route; this would cause the route to bounce
back and forth, which would generate an intolerable number of
triggered updates. However, if the existing route is showing signs
of timing out, it may be better to switch to an equally-good
alternative route immediately, rather than waiting for the timeout to
happen. Therefore, if the new metric is the same as the old one,
examine the timeout for the existing route"""
    print(">>>>>>>>>>>router change flag is {} metric is {} ".format(routeChange,metric))
    if metric < 16:
        table_item = {
                        "destination": destination,
                        "metric": metric, 
                        "next_hop_id": nextHop,
                        "router_change_flag" : routeChange,
                        "garbage_collect_start": None,
                        "last_update_time": time.time()
                    }
        index = getIndexFromTable(destination)
        routing_table[index] = table_item
    else:
        if routeChange:
           
            table_item = {
                            "destination": destination,
                            "metric": metric, 
                            "next_hop_id": nextHop,
                            "router_change_flag" : routeChange,
                            "garbage_collect_start": time.time(),
                            "last_update_time": None
                        }
            index = getIndexFromTable(destination)
            routing_table[index] = table_item
            
            sendPacket(True) #send the updated route only
    
    printTable()        

########################print the whole routing table    #######################      
def printTable():
    """print the RIP routing table"""
    
    global my_router_id
      
    print("+--------------------------------------------------------------+")
    print("|Destination|Metric|Next Hop Id|Route Change|Timeout|Garbage|")
    print("+--------------------------------------------------------------+")

    content_format = "|{0:^11}|{1:^6}|{2:^11}|{3:^12}|{4:^7}|{5:^7}|"
    for item in routing_table:      
        if item['destination'] != my_router_id:
            if(item['last_update_time'] is None):
                timeout = '-'
            else:
                timeout = int(time.time()-item['last_update_time'])
            
            if(item['garbage_collect_start'] is None):
                garbage = '-'
            else:
                garbage = int(time.time()-item['garbage_collect_start'])
            
            if(item['router_change_flag'] is None):
                router_change = '-'
            else:
                router_change = item['router_change_flag']
            print(content_format.format(item['destination'], item['metric'], 
                             item['next_hop_id'],router_change,timeout,garbage))
        


def main():
    """main entrance"""
    fileName = sys.argv[1]
    #start read configure file
    loadConfigFile(fileName)
    
    initListenSocket()#start listenthreads
    initPeriodicTimer()#init the periodic timer
    initTimeoutTimer()#init timeout timer
    initGarbageCollectionTimer()#init garbage collection timer
    
    
    recvPacket()    

main()
