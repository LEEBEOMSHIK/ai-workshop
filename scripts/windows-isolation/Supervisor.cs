using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
namespace Workshop.Isolation {
internal static class Supervisor {
    private static volatile bool cancelled;
    private static void Emit(string phase,string status,string code) {Console.WriteLine("phase="+phase+" status="+status+" code="+code);}
    private static string Quote(string s) {if(s.Contains("\"") || s.EndsWith("\\")) throw new ProbeException("unsafe_argument"); return "\""+s+"\"";}
    private static IntPtr OpenInherited(string path,uint access,uint disposition) {
        Native.SECURITY_ATTRIBUTES sa=new Native.SECURITY_ATTRIBUTES(); sa.Length=Marshal.SizeOf(sa); sa.Inherit=true;
        IntPtr h=Native.CreateFileW(path,access,3,ref sa,disposition,Native.FILE_ATTRIBUTE_NORMAL,IntPtr.Zero);
        if(h==Native.INVALID_HANDLE_VALUE) throw new ProbeException("stdio_open_"+Marshal.GetLastWin32Error()); return h;
    }
    private static TcpListener Listen(IPAddress address) {
        TcpListener listener=new TcpListener(address,0); listener.Start(2);
        try {
            // Positive control proves that this is a real reachable controlled listener.
            using(TcpClient control=new TcpClient(address.AddressFamily)) {
                control.Connect((IPEndPoint)listener.LocalEndpoint);
                using(TcpClient accepted=listener.AcceptTcpClient()) { }
            }
            return listener;
        } catch {listener.Stop(); throw;}
    }
    public static int Main(string[] args) {
        if(args.Length!=5 || (args[0]!="preflight" && args[0]!="run")) {Emit("input","FAILED","usage"); return 64;}
        SecurityScope scope=null; IntPtr job=IntPtr.Zero,input=IntPtr.Zero,output=IntPtr.Zero,environment=IntPtr.Zero;
        Native.PROCESS_INFORMATION pi=new Native.PROCESS_INFORMATION(); TcpListener ipv4=null,ipv6=null;
        int result=30; bool processStopped=true; string phase="validation";
        Console.CancelKeyPress+=delegate(object sender,ConsoleCancelEventArgs e) {e.Cancel=true; cancelled=true;};
        try {
            if(args[0]=="run") Contract.RequireNativeRunReady();
            string root=Contract.Canonical(args[1]); int timeout;
            if(!Int32.TryParse(args[4],out timeout)) throw new ProbeException("invalid_timeout"); Contract.Timeout(timeout);
            if(!Regex.IsMatch(args[2],"^[a-f0-9]{32}$")) throw new ProbeException("invalid_run_id");
            string binaryDir=Contract.Canonical(Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location));
            if(!String.Equals(Directory.GetParent(binaryDir).FullName,root,StringComparison.OrdinalIgnoreCase) || !root.EndsWith(@"\.local-data\project-agent-work\codex-os-isolation-probe",StringComparison.OrdinalIgnoreCase)) throw new ProbeException("artifact_root_mismatch");
            string source=Contract.Child(binaryDir,"Canary.exe"); Contract.VerifyHash(source,args[3]);
            scope=new SecurityScope(root,args[2]);
            if(Directory.Exists(scope.Root) || File.Exists(scope.Root)) throw new ProbeException("run_directory_not_fresh");
            if(args[0]=="preflight") {
                Console.WriteLine("profile="+scope.Profile);
                Console.WriteLine("run_directory="+scope.Root);
                Console.WriteLine("ace="+scope.Root+";ReadAndExecute;no_inheritance");
                Console.WriteLine("ace="+Path.Combine(scope.Root,"Canary.exe")+";ReadAndExecute;no_inheritance");
                Console.WriteLine("ace="+Path.Combine(scope.Root,"scratch.dat")+";Read,Write;no_inheritance");
                Console.WriteLine("mandatory_label="+Path.Combine(scope.Root,"scratch.dat")+";S:(ML;;NW;;;LW);read_back_verified;original_restored_on_cleanup");
                Console.WriteLine("artifact_budget_bytes="+(new FileInfo(source).Length+16384));
                Console.WriteLine("cleanup=owned_profile_and_exact_three_aces;artifact_files_preserved");
                Console.WriteLine("cli_allowed=false;mandatory_unimplemented=nonloopback,timeout_integration,cancel_integration,supervisor_death_integration");
                return 0;
            }
            phase="prepare"; scope.Prepare(source,args[3]); Emit(phase,"PASS","owned_scope_created");
            phase="listeners"; ipv4=Listen(IPAddress.Loopback);
            try {ipv6=Listen(IPAddress.IPv6Loopback);} catch(SocketException) {Emit("listener6","NOTRUN","unavailable");}
            string protocol=Path.Combine(scope.Root,"canary.protocol");
            input=OpenInherited("NUL",Native.GENERIC_READ|Native.GENERIC_WRITE,Native.OPEN_EXISTING);
            output=OpenInherited(protocol,Native.GENERIC_WRITE,Native.CREATE_NEW);
            phase="job"; job=Native.CreateJobObjectW(IntPtr.Zero,null);
            if(job==IntPtr.Zero) throw new ProbeException("job_create_failed");
            Native.EXTENDED_LIMIT limits=new Native.EXTENDED_LIMIT();
            limits.Basic.LimitFlags=Native.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE|Native.JOB_OBJECT_LIMIT_ACTIVE_PROCESS;
            limits.Basic.ActiveProcessLimit=1; // No breakaway or silent-breakaway flags.
            if(!Native.SetInformationJobObject(job,Native.JobObjectExtendedLimitInformation,ref limits,Marshal.SizeOf(limits))) throw new ProbeException("job_limits_failed");
            string shell=Path.Combine(Environment.SystemDirectory,"cmd.exe");
            string command=Quote(scope.Executable)+" synthetic-v1 "+Quote(scope.Scratch)+" "+Quote(scope.Protected)+" "+Quote(shell)+" "+Native.GetCurrentProcessId()+" "+((IPEndPoint)ipv4.LocalEndpoint).Port+" "+(ipv6==null?0:((IPEndPoint)ipv6.LocalEndpoint).Port);
            // Empty environment: do not inherit credentials, proxy configuration or developer paths.
            environment=Marshal.StringToHGlobalUni("\0\0");
            LaunchGate gate=new LaunchGate();
            using(LaunchAttributes attributes=new LaunchAttributes()) {
                attributes.Configure(scope.Sid,input,output);
                Native.STARTUPINFOEX start=new Native.STARTUPINFOEX(); start.StartupInfo.cb=Marshal.SizeOf(start);
                start.StartupInfo.flags=Native.STARTF_USESTDHANDLES; start.StartupInfo.input=input; start.StartupInfo.output=output; start.StartupInfo.error=input; start.AttributeList=attributes.Pointer;
                phase="create_suspended";
                Contract.VerifyHash(scope.Executable,args[3]); Contract.Canonical(scope.Root);
                if(!Native.CreateProcessW(scope.Executable,new StringBuilder(command),IntPtr.Zero,IntPtr.Zero,true,Native.CREATE_SUSPENDED|Native.EXTENDED_STARTUPINFO_PRESENT|Native.CREATE_UNICODE_ENVIRONMENT|Native.CREATE_NO_WINDOW,environment,scope.Root,ref start,out pi)) throw new ProbeException("create_process_"+Marshal.GetLastWin32Error());
                processStopped=false; gate.Created();
                if(!Native.AssignProcessToJobObject(job,pi.Process)) throw new ProbeException("job_assignment_failed"); gate.JobAssigned();
                phase="token_policy"; LaunchVerification.Verify(pi.Process,scope.Sid,job); gate.TokenVerified(); Emit(phase,"PASS","lpac_zero_capabilities_child_restricted");
                gate.BeforeResume(); if(Native.ResumeThread(pi.Thread)==UInt32.MaxValue) throw new ProbeException("resume_failed"); Emit("resume","PASS","verified_before_resume");
            }
            // Prevent inheritance by any subsequently started host process.
            Native.SetHandleInformation(input,1,0); Native.SetHandleInformation(output,1,0);
            phase="canary"; Stopwatch timer=Stopwatch.StartNew(); bool timedOut=false;
            while(true) {
                uint wait=Native.WaitForSingleObject(pi.Process,50);
                if(wait==Native.WAIT_OBJECT_0) {processStopped=true; break;}
                if(wait!=Native.WAIT_TIMEOUT) throw new ProbeException("process_wait_failed");
                if(new FileInfo(protocol).Length>8192) throw new ProbeException("report_oversize");
                if(cancelled || timer.ElapsedMilliseconds>=timeout) {timedOut=!cancelled; break;}
            }
            if(!processStopped) {
                if(!Native.TerminateJobObject(job,91) || Native.WaitForSingleObject(pi.Process,5000)!=Native.WAIT_OBJECT_0) throw new ProbeException("termination_unverified");
                processStopped=true;
            }
            uint exit; if(!Native.GetExitCodeProcess(pi.Process,out exit)) throw new ProbeException("exit_query_failed");
            Native.CloseHandle(output); output=IntPtr.Zero;
            if(cancelled || timedOut) {Emit(phase,"FAILED",cancelled?"cancelled":"timeout"); result=40;}
            else {
                string report;
                using(FileStream f=new FileStream(protocol,FileMode.Open,FileAccess.Read,FileShare.Read)) {
                    if(f.Length>8192) throw new ProbeException("report_oversize");
                    using(StreamReader reader=new StreamReader(f,Encoding.ASCII)) report=reader.ReadToEnd();
                }
                bool passed=Contract.AcceptReport(report,exit,false);
                // Validated fixed protocol contains only field identifiers and numeric native codes.
                foreach(string line in report.Split('\n')) if(line.Trim().Length>0) Console.WriteLine("canary_"+line.Trim());
                if(ipv4.Pending() || (ipv6!=null && ipv6.Pending())) throw new ProbeException("listener_connection_observed");
                byte[] scratch=File.ReadAllBytes(scope.Scratch);
                if(scratch.Length!=2 || scratch[0]!=41 || scratch[1]!=43) passed=false;
                Emit(phase,passed?"PASS":"FAILED",passed?"synthetic_canary_passed":"startup_or_canary_failed_"+exit);
                result=passed?20:30;
            }
        } catch(ProbeException e) {Emit(phase,"FAILED",e.Code); result=30;}
        catch(Exception e) {Emit(phase,"FAILED","host_exception_"+unchecked((uint)Marshal.GetHRForException(e))); result=30;}
        finally {
            if(pi.Process!=IntPtr.Zero && !processStopped) {
                if(job!=IntPtr.Zero) Native.TerminateJobObject(job,92);
                Native.TerminateProcess(pi.Process,92);
                processStopped=Native.WaitForSingleObject(pi.Process,5000)==Native.WAIT_OBJECT_0;
            }
            if(job!=IntPtr.Zero) {
                Native.JOB_ACCOUNTING accounting;
                if(!Native.QueryInformationJobObject(job,Native.JobObjectBasicAccountingInformation,out accounting,Marshal.SizeOf(typeof(Native.JOB_ACCOUNTING)),IntPtr.Zero) || accounting.ActiveProcesses!=0) {Emit("cleanup","FAILED","job_not_empty"); processStopped=false;}
                Native.CloseHandle(job);
            }
            if(pi.Thread!=IntPtr.Zero) Native.CloseHandle(pi.Thread); if(pi.Process!=IntPtr.Zero) Native.CloseHandle(pi.Process);
            if(input!=IntPtr.Zero) Native.CloseHandle(input); if(output!=IntPtr.Zero) Native.CloseHandle(output);
            if(environment!=IntPtr.Zero) Marshal.FreeHGlobal(environment);
            if(ipv4!=null) ipv4.Stop(); if(ipv6!=null) ipv6.Stop();
            if(scope!=null && processStopped) {scope.Dispose(); if(scope.CleanupFailed) {Emit("cleanup","FAILED","owned_cleanup_failed"); result=50;}}
            else if(!processStopped) {Emit("cleanup","FAILED","process_exit_unverified_profile_aces_preserved"); result=50;}
        }
        Emit("acceptance","INCOMPLETE","cli_blocked_nonloopback_and_lifecycle_integration_not_exercised");
        return result;
    }
}
}
