using System;
using System.Runtime.InteropServices;
using System.Text;
namespace Workshop.Isolation {
internal static class Native {
    internal const uint CREATE_SUSPENDED=0x4, EXTENDED_STARTUPINFO_PRESENT=0x80000, CREATE_UNICODE_ENVIRONMENT=0x400, CREATE_NO_WINDOW=0x8000000, CREATE_BREAKAWAY_FROM_JOB=0x1000000;
    internal const int STARTF_USESTDHANDLES=0x100;
    internal const long PROC_THREAD_ATTRIBUTE_HANDLE_LIST=0x20002, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES=0x20009, PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY=0x2000f, PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY=0x2000e;
    internal const int PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT=1, PROCESS_CREATION_CHILD_PROCESS_RESTRICTED=1;
    internal const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x2000, JOB_OBJECT_LIMIT_ACTIVE_PROCESS=0x8;
    internal const uint TOKEN_QUERY=8, PROCESS_QUERY_LIMITED_INFORMATION=0x1000, PROCESS_VM_WRITE=0x20, PROCESS_CREATE_PROCESS=0x80;
    internal const uint WAIT_OBJECT_0=0, WAIT_TIMEOUT=258, INFINITE=0xffffffff;
    internal const int TokenIsAppContainer=29, TokenCapabilities=30, TokenAppContainerSid=31, TokenIsLessPrivilegedAppContainer=46;
    internal const int ProcessChildProcessPolicy=13, JobObjectExtendedLimitInformation=9, JobObjectBasicAccountingInformation=1;
    internal const uint GENERIC_READ=0x80000000, GENERIC_WRITE=0x40000000, OPEN_EXISTING=3, CREATE_NEW=1, FILE_ATTRIBUTE_NORMAL=0x80;
    internal static readonly IntPtr INVALID_HANDLE_VALUE=new IntPtr(-1);
    [StructLayout(LayoutKind.Sequential)] internal struct SECURITY_ATTRIBUTES { public int Length; public IntPtr Descriptor; [MarshalAs(UnmanagedType.Bool)] public bool Inherit; }
    [StructLayout(LayoutKind.Sequential)] internal struct SECURITY_CAPABILITIES { public IntPtr AppContainerSid, Capabilities; public uint CapabilityCount, Reserved; }
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] internal struct STARTUPINFO { public int cb; public string reserved,desktop,title; public uint x,y,xSize,ySize,xCount,yCount,fill; public int flags; public short show,reserved2; public IntPtr reservedBytes,input,output,error; }
    [StructLayout(LayoutKind.Sequential)] internal struct STARTUPINFOEX { public STARTUPINFO StartupInfo; public IntPtr AttributeList; }
    [StructLayout(LayoutKind.Sequential)] internal struct PROCESS_INFORMATION { public IntPtr Process,Thread; public uint ProcessId,ThreadId; }
    [StructLayout(LayoutKind.Sequential)] internal struct BASIC_LIMIT { public long PerProcessTime,PerJobTime; public uint LimitFlags; public UIntPtr MinWorkingSet,MaxWorkingSet; public uint ActiveProcessLimit; public UIntPtr Affinity; public uint Priority,Scheduling; }
    [StructLayout(LayoutKind.Sequential)] internal struct IO_COUNTERS { public ulong ReadOperations,WriteOperations,OtherOperations,ReadBytes,WriteBytes,OtherBytes; }
    [StructLayout(LayoutKind.Sequential)] internal struct EXTENDED_LIMIT { public BASIC_LIMIT Basic; public IO_COUNTERS Io; public UIntPtr ProcessMemory,JobMemory,PeakProcessMemory,PeakJobMemory; }
    [StructLayout(LayoutKind.Sequential)] internal struct JOB_ACCOUNTING { public long UserTime,KernelTime,PeriodUser,PeriodKernel; public uint PageFaults,TotalProcesses,ActiveProcesses,TerminatedProcesses; }
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool InitializeProcThreadAttributeList(IntPtr list,int count,int flags,ref IntPtr size);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool UpdateProcThreadAttribute(IntPtr list,uint flags,IntPtr attribute,IntPtr value,IntPtr size,IntPtr previous,IntPtr returned);
    [DllImport("kernel32.dll")] internal static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] internal static extern bool CreateProcessW(string app,StringBuilder command,IntPtr processAttrs,IntPtr threadAttrs,bool inherit,uint flags,IntPtr environment,string cwd,ref STARTUPINFOEX start,out PROCESS_INFORMATION pi);
    [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] internal static extern IntPtr CreateJobObjectW(IntPtr attrs,string name);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool SetInformationJobObject(IntPtr job,int info,ref EXTENDED_LIMIT value,int length);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool QueryInformationJobObject(IntPtr job,int info,out JOB_ACCOUNTING value,int length,IntPtr returned);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool AssignProcessToJobObject(IntPtr job,IntPtr process);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool IsProcessInJob(IntPtr process,IntPtr job,out bool result);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool TerminateJobObject(IntPtr job,uint code);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool TerminateProcess(IntPtr process,uint code);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern uint WaitForSingleObject(IntPtr handle,uint millis);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool GetExitCodeProcess(IntPtr process,out uint code);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern IntPtr OpenProcess(uint access,bool inherit,uint pid);
    [DllImport("kernel32.dll")] internal static extern uint GetCurrentProcessId();
    [DllImport("kernel32.dll")] internal static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool GetProcessMitigationPolicy(IntPtr process,int policy,out uint flags,int length);
    [DllImport("advapi32.dll",SetLastError=true)] internal static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
    [DllImport("advapi32.dll",SetLastError=true)] internal static extern bool GetTokenInformation(IntPtr token,int info,IntPtr buffer,int length,out int returned);
    [DllImport("advapi32.dll")] internal static extern bool EqualSid(IntPtr first,IntPtr second);
    [DllImport("userenv.dll",CharSet=CharSet.Unicode)] internal static extern int CreateAppContainerProfile(string name,string display,string description,IntPtr capabilities,uint count,out IntPtr sid);
    [DllImport("userenv.dll",CharSet=CharSet.Unicode)] internal static extern int DeleteAppContainerProfile(string name);
    [DllImport("userenv.dll",CharSet=CharSet.Unicode)] internal static extern int DeriveAppContainerSidFromAppContainerName(string name,out IntPtr sid);
    [DllImport("advapi32.dll")] internal static extern IntPtr FreeSid(IntPtr sid);
    [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] internal static extern IntPtr CreateFileW(string path,uint access,uint share,ref SECURITY_ATTRIBUTES attrs,uint disposition,uint flags,IntPtr template);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool WriteFile(IntPtr file,byte[] data,uint count,out uint written,IntPtr overlapped);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool ReadFile(IntPtr file,byte[] data,uint count,out uint read,IntPtr overlapped);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool SetHandleInformation(IntPtr handle,uint mask,uint flags);
    [DllImport("kernel32.dll",SetLastError=true)] internal static extern bool GetFileInformationByHandle(IntPtr handle,out FILE_INFORMATION info);
    [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] internal static extern bool CreateDirectoryW(string path,IntPtr attrs);
    [DllImport("advapi32.dll")] internal static extern uint GetSecurityInfo(IntPtr handle,int objectType,uint information,out IntPtr owner,out IntPtr group,out IntPtr dacl,out IntPtr sacl,out IntPtr descriptor);
    [DllImport("advapi32.dll")] internal static extern uint SetSecurityInfo(IntPtr handle,int objectType,uint information,IntPtr owner,IntPtr group,IntPtr dacl,IntPtr sacl);
    [DllImport("advapi32.dll")] internal static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("advapi32.dll",SetLastError=true)] internal static extern bool GetSecurityDescriptorDacl(IntPtr descriptor,out bool present,out IntPtr dacl,out bool defaulted);
    [DllImport("advapi32.dll",SetLastError=true)] internal static extern bool GetSecurityDescriptorSacl(IntPtr descriptor,out bool present,out IntPtr sacl,out bool defaulted);
    [DllImport("kernel32.dll")] internal static extern IntPtr LocalFree(IntPtr memory);
    [StructLayout(LayoutKind.Sequential)] internal struct FILE_INFORMATION { public uint Attributes,CreateLow,CreateHigh,AccessLow,AccessHigh,WriteLow,WriteHigh,Volume,SizeHigh,SizeLow,Links,IndexHigh,IndexLow; }
}
}
