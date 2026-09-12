using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
namespace Workshop.Isolation {
internal static class Canary {
    private static void Result(string key,string status,uint code) { Console.WriteLine(key+"="+status+":"+code); }
    private static Native.SECURITY_ATTRIBUTES Attributes() { Native.SECURITY_ATTRIBUTES sa=new Native.SECURITY_ATTRIBUTES(); sa.Length=Marshal.SizeOf(sa); return sa; }
    private static void Scratch(string path) {
        Native.SECURITY_ATTRIBUTES sa=Attributes();
        IntPtr h=Native.CreateFileW(path,Native.GENERIC_READ|Native.GENERIC_WRITE,0,ref sa,Native.OPEN_EXISTING,Native.FILE_ATTRIBUTE_NORMAL,IntPtr.Zero);
        if(h==Native.INVALID_HANDLE_VALUE) { Result("scratch","FAIL",(uint)Marshal.GetLastWin32Error()); return; }
        try {
            byte[] data=new byte[1]; uint count;
            bool read=Native.ReadFile(h,data,1,out count,IntPtr.Zero) && count==1 && data[0]==41;
            bool write=Native.WriteFile(h,new byte[]{43},1,out count,IntPtr.Zero) && count==1;
            Result("scratch",read&&write?"PASS":"FAIL",read&&write?0u:(uint)Marshal.GetLastWin32Error());
        } finally {Native.CloseHandle(h);}
    }
    private static void Protected(string path,string key,uint access) {
        Native.SECURITY_ATTRIBUTES sa=Attributes();
        IntPtr h=Native.CreateFileW(path,access,3,ref sa,Native.OPEN_EXISTING,Native.FILE_ATTRIBUTE_NORMAL,IntPtr.Zero);
        if(h!=Native.INVALID_HANDLE_VALUE) {Native.CloseHandle(h); Result(key,"FAIL",0); return;}
        uint code=(uint)Marshal.GetLastWin32Error(); Result(key,code==5?"PASS":"NOTRUN",code);
    }
    private static void Spawn(string key,string executable,uint flags) {
        Native.STARTUPINFOEX start=new Native.STARTUPINFOEX(); start.StartupInfo.cb=Marshal.SizeOf(typeof(Native.STARTUPINFO));
        Native.PROCESS_INFORMATION pi;
        // If denied policy is broken, the child remains suspended and is killed before any code executes.
        bool ok=Native.CreateProcessW(executable,new StringBuilder("\""+executable+"\""),IntPtr.Zero,IntPtr.Zero,false,flags|Native.CREATE_SUSPENDED|Native.CREATE_NO_WINDOW,IntPtr.Zero,null,ref start,out pi);
        uint code=(uint)Marshal.GetLastWin32Error();
        if(ok) {
            Native.TerminateProcess(pi.Process,90); Native.WaitForSingleObject(pi.Process,2000);
            Native.CloseHandle(pi.Thread); Native.CloseHandle(pi.Process); Result(key,"FAIL",0);
        } else Result(key,code==5?"PASS":"NOTRUN",code);
    }
    private static void Connect(string key,IPAddress address,int port) {
        if(port==0) {Result(key,"NOTRUN",0); return;}
        using(Socket s=new Socket(address.AddressFamily,SocketType.Stream,ProtocolType.Tcp)) {
            try {
                IAsyncResult pending=s.BeginConnect(new IPEndPoint(address,port),null,null);
                using(System.Threading.WaitHandle wait=pending.AsyncWaitHandle) {
                    if(!wait.WaitOne(1000)) {Result(key,"NOTRUN",10060); return;}
                    s.EndConnect(pending);
                }
                Result(key,"FAIL",0);
            } catch(SocketException e) {Result(key,e.SocketErrorCode==SocketError.AccessDenied?"PASS":"NOTRUN",(uint)e.ErrorCode);}
        }
    }
    private static uint ProbeHandle(uint pid,uint right) {
        IntPtr handle=Native.OpenProcess(right,false,pid);
        uint code=(uint)Marshal.GetLastWin32Error();
        if(handle==IntPtr.Zero) return code;
        Native.CloseHandle(handle); return 0;
    }
    private static bool IsLpac() {
        IntPtr token;
        if(!Native.OpenProcessToken(Native.GetCurrentProcess(),Native.TOKEN_QUERY,out token)) return false;
        IntPtr value=IntPtr.Zero;
        try {
            value=Marshal.AllocHGlobal(4);
            foreach(int field in new int[]{Native.TokenIsAppContainer,Native.TokenIsLessPrivilegedAppContainer}) {
                int returned;
                if(!Native.GetTokenInformation(token,field,value,4,out returned) || returned!=4 || Marshal.ReadInt32(value)!=1) return false;
            }
            return true;
        } finally {if(value!=IntPtr.Zero) Marshal.FreeHGlobal(value); Native.CloseHandle(token);}
    }
    public static int Main(string[] args) {
        // Only the exact synthetic protocol emitted by the supervisor is accepted.
        if(args.Length!=7 || args[0]!="synthetic-v1") return 64;
        uint pid; int ipv4,ipv6;
        if(!UInt32.TryParse(args[4],out pid) || !Int32.TryParse(args[5],out ipv4) || !Int32.TryParse(args[6],out ipv6) || ipv4<0 || ipv4>65535 || ipv6<0 || ipv6>65535) return 64;
        try {
            // Refuse standalone host invocation before fixture IO or process probes.
            if(!IsLpac()) return 65;
            string self=System.Reflection.Assembly.GetExecutingAssembly().Location;
            Contract.SyntheticInputs(self,args[1],args[2],args[3]);
            Scratch(args[1]); Protected(args[2],"protected_read",Native.GENERIC_READ); Protected(args[2],"protected_write",Native.GENERIC_WRITE);
            Spawn("child",self,0); Spawn("shell",args[3],0); Spawn("breakaway",self,Native.CREATE_BREAKAWAY_FROM_JOB);
            uint createProcess=ProbeHandle(pid,Native.PROCESS_CREATE_PROCESS),vmWrite=ProbeHandle(pid,Native.PROCESS_VM_WRITE);
            bool denied=SecurityContract.PrivilegedHandlesDenied(createProcess,vmWrite);
            Result("process_handle",denied?"PASS":(createProcess==0 || vmWrite==0)?"FAIL":"NOTRUN",denied?5:Math.Min(createProcess,vmWrite));
            Connect("network4",IPAddress.Loopback,ipv4); Connect("network6",IPAddress.IPv6Loopback,ipv6);
            return 0;
        } catch(Exception) {return 70;}
    }
}
}
