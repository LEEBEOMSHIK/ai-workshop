using System;
using System.IO;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
namespace Workshop.Isolation {
internal sealed class ProbeException : Exception { public string Code; public ProbeException(string code) { Code=code; } }
internal static class Contract {
    public static void RequireNativeRunReady() {
        // Deliberately no flag/configuration bypass. Atomic creation-to-handle
        // ownership and lifecycle integration must be implemented and reviewed
        // before this draft can enable native mutations.
        throw new ProbeException("native_run_disabled_ownership_lifecycle_unverified");
    }
    public static void SyntheticInputs(string executable,string scratch,string protectedFile,string shell) {
        string directory=Path.GetDirectoryName(executable);
        if(directory==null || !Regex.IsMatch(directory,@"(?i)\\\.local-data\\project-agent-work\\codex-os-isolation-probe\\run-[a-f0-9]{32}$") ||
            !String.Equals(Path.GetFileName(executable),"Canary.exe",StringComparison.OrdinalIgnoreCase) ||
            !String.Equals(scratch,Path.Combine(directory,"scratch.dat"),StringComparison.OrdinalIgnoreCase) ||
            !String.Equals(protectedFile,Path.Combine(directory,"protected.dat"),StringComparison.OrdinalIgnoreCase) ||
            !String.Equals(shell,Path.Combine(Environment.SystemDirectory,"cmd.exe"),StringComparison.OrdinalIgnoreCase)) throw new ProbeException("canary_input_out_of_scope");
    }
    public static void VerifyHash(string path,string hash) {
        if(!Regex.IsMatch(hash,"^[0-9a-fA-F]{64}$")) throw new ProbeException("invalid_hash");
        using(FileStream f = new FileStream(Canonical(path),FileMode.Open,FileAccess.Read,FileShare.Read))
        using(SHA256 sha=SHA256.Create())
            if(!String.Equals(BitConverter.ToString(sha.ComputeHash(f)).Replace("-",""),hash,StringComparison.OrdinalIgnoreCase)) throw new ProbeException("hash_mismatch");
    }
    public static void Timeout(int n) { if(n<100 || n>60000) throw new ProbeException("invalid_timeout"); }
    public static string Canonical(string path) {
        if(String.IsNullOrEmpty(path) || !Regex.IsMatch(path,@"^[A-Za-z]:[\\/]") || path.Substring(2).Contains(":")) throw new ProbeException("unsafe_path");
        foreach(string part in path.Substring(3).Split('\\','/'))
            if(part==".." || part=="." || part.EndsWith(" ") || part.EndsWith(".")) throw new ProbeException("unsafe_path");
        string full=Path.GetFullPath(path).TrimEnd('\\');
        string cursor=full;
        while(!String.IsNullOrEmpty(cursor)) {
            if(File.Exists(cursor) || Directory.Exists(cursor)) CheckAttributes(File.GetAttributes(cursor));
            cursor=Path.GetDirectoryName(cursor);
        }
        return full;
    }
    public static void CheckAttributes(FileAttributes attrs) { if((attrs & FileAttributes.ReparsePoint)!=0) throw new ProbeException("reparse_path"); }
    public static string Child(string root,string relative) {
        string full=Canonical(Path.Combine(root,relative));
        if(!full.StartsWith(Canonical(root)+"\\",StringComparison.OrdinalIgnoreCase)) throw new ProbeException("unsafe_path");
        return full;
    }
    public static readonly string[] CanaryGates={"scratch","protected_read","protected_write","child","shell","breakaway","process_handle","network4","network6"};
    public static bool AcceptReport(string value,uint exit,bool timeout) {
        if(value.Length>8192) throw new ProbeException("report_oversize");
        HashSet<string> seen=new HashSet<string>(); bool passed=true;
        foreach(string raw in value.Split('\n')) {
            string line=raw.TrimEnd('\r'); if(line.Length==0) continue;
            Match m=Regex.Match(line,@"^([a-z0-9_]+)=(PASS|FAIL|NOTRUN):([0-9]{1,10})$"); uint code;
            if(!m.Success || Array.IndexOf(CanaryGates,m.Groups[1].Value)<0 || !seen.Add(m.Groups[1].Value) || !UInt32.TryParse(m.Groups[3].Value,out code)) throw new ProbeException("report_invalid");
            string key=m.Groups[1].Value;
            bool codeOk=key=="scratch" ? code==0 : key.StartsWith("network") ? code==10013 : code==5;
            if(m.Groups[2].Value!="PASS" || !codeOk) passed=false;
        }
        return passed && seen.Count==CanaryGates.Length && exit==0 && !timeout;
    }
}
internal sealed class LaunchGate {
    private bool created,job,token,resumed;
    public void Created() { created=true; } public void JobAssigned() { job=true; } public void TokenVerified() { token=true; }
    public void BeforeResume() { if(!created || !job || !token || resumed) throw new ProbeException("resume_not_verified"); resumed=true; }
}
internal sealed class OwnedChanges : IDisposable {
    private readonly Stack<Action> actions=new Stack<Action>();
    public bool CleanupFailed { get; private set; }
    public void Add(Action undo) { actions.Push(undo); }
    public void Dispose() { while(actions.Count>0) { try { actions.Pop()(); } catch(Exception) { CleanupFailed=true; } } }
}
}
