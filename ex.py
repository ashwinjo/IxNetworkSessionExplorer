from ixnetwork_restpy import SessionAssistant

CHASSIS_IP = "10.36.65.163"
API_SERVER  = "10.36.236.121"   # same host — adjust if API server differs
REST_PORT   = 443               # 443 = Web/Linux Edition; 11009 = Windows GUI
USERNAME    = "admin"
PASSWORD    = "Kimchi123Kimchi123!"

session = SessionAssistant(
    IpAddress=API_SERVER,
    RestPort=REST_PORT,
    UserName=USERNAME,
    Password=PASSWORD,
    SessionId=3,
    ClearConfig=False,          # attach to existing sessions — do NOT wipe config
    LogLevel=SessionAssistant.LOGLEVEL_WARNING,
)

ixnetwork = session.Ixnetwork

# Fetch all vports, then filter to those assigned to the target chassis
all_vports = ixnetwork.Vport.find()
print(all_vports)
chassis_vports = [
    vp for vp in all_vports
    if vp.AssignedTo.startswith(CHASSIS_IP)
]

if not chassis_vports:
    print(f"No vports assigned to chassis {CHASSIS_IP}")
else:
    print(f"Found {len(chassis_vports)} vport(s) on chassis {CHASSIS_IP}\n")
    for vp in chassis_vports:
        print(f"  Name            : {vp.Name}")
        print(f"  AssignedTo      : {vp.AssignedTo}")          # ip:card:port
        print(f"  ConnectionState : {vp.ConnectionState}")     # unassigned/connectedLinkUp/etc.
        print(f"  ConnectionStatus: {vp.ConnectionStatus}")
        print(f"  Type            : {vp.Type}")                # ethernet/atm/etc.
        print(f"  ActualSpeed     : {vp.ActualSpeed}")         # Mbps
        print(f"  RxMode          : {vp.RxMode}")
        print(f"  TxMode          : {vp.TxMode}")
        print(f"  IsConnected     : {vp.IsConnected}")
        print("-" * 50)