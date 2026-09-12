using System;
using System.Collections.Generic;
using System.IO;
using System.Security.AccessControl;
using System.Security.Principal;
namespace Workshop.Isolation {
internal static class ContractTests {
    private static int failures;
    private static void Check(string name, Action action) {
        try { action(); Console.WriteLine("PASS " + name); }
        catch (Exception) { failures++; Console.WriteLine("FAIL " + name); }
    }
    private static void Reject(string code, Action action) {
        try { action(); } catch (ProbeException e) { if(e.Code == code) return; throw; }
        throw new Exception("accepted unsafe input");
    }
    private static void Require(bool value) { if(!value) throw new Exception("wrong result"); }
    public static int Main(string[] args) {
        string fixture = Path.Combine(args[0], "contract-fixture-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(fixture);
        string exe = Path.Combine(fixture, "Canary.exe");
        File.WriteAllText(exe, "synthetic");
        Check("hash mismatch rejected", delegate { Reject("hash_mismatch", delegate { Contract.VerifyHash(exe, new string('0',64)); }); });
        Check("invalid timeouts rejected", delegate { foreach(int n in new int[]{-1,0,99,60001}) Reject("invalid_timeout", delegate { Contract.Timeout(n); }); });
        Check("unsafe relative path rejected", delegate { Reject("unsafe_path", delegate { Contract.Canonical("..\\outside"); }); });
        Check("alternate data stream rejected", delegate { Reject("unsafe_path", delegate { Contract.Canonical(exe + ":stream"); }); });
        Check("reparse attribute rejected", delegate { Reject("reparse_path", delegate { Contract.CheckAttributes(FileAttributes.Directory | FileAttributes.ReparsePoint); }); });
        Check("empty report incomplete", delegate { Require(!Contract.AcceptReport("",0,false)); });
        Check("timeout never passes", delegate { Require(!Contract.AcceptReport("scratch=PASS:0\n",0,true)); });
        Check("exit failure never passes", delegate { Require(!Contract.AcceptReport("scratch=PASS:0\n",1,false)); });
        Check("oversized report rejected", delegate { Reject("report_oversize", delegate { Contract.AcceptReport(new string('x',8193),0,false); }); });
        Check("unknown report field rejected", delegate { Reject("report_invalid", delegate { Contract.AcceptReport("secret=PASS:0\n",0,false); }); });
        Check("duplicate report field rejected", delegate { Reject("report_invalid", delegate { Contract.AcceptReport("scratch=PASS:0\nscratch=PASS:0\n",0,false); }); });
        Check("denial timeout is incomplete", delegate { Require(!Contract.AcceptReport("scratch=PASS:0\nnetwork4=PASS:10060\n",0,false)); });
        Check("resume blocked without token verification", delegate { LaunchGate g = new LaunchGate(); g.Created(); g.JobAssigned(); Reject("resume_not_verified", delegate { g.BeforeResume(); }); });
        Check("resume blocked without job", delegate { LaunchGate g = new LaunchGate(); g.Created(); g.TokenVerified(); Reject("resume_not_verified", delegate { g.BeforeResume(); }); });
        Check("verified suspended process can resume once", delegate { LaunchGate g = new LaunchGate(); g.Created(); g.JobAssigned(); g.TokenVerified(); g.BeforeResume(); Reject("resume_not_verified", delegate { g.BeforeResume(); }); });
        Check("owned cleanup unwinds reverse order after failure", delegate { List<int> seen = new List<int>(); using(OwnedChanges changes = new OwnedChanges()) { changes.Add(delegate {seen.Add(1);}); changes.Add(delegate {seen.Add(2); throw new IOException();}); changes.Add(delegate {seen.Add(3);}); } Require(seen.Count==3 && seen[0]==3 && seen[1]==2 && seen[2]==1); });
        Check("each privileged handle right must be denied", delegate { Require(SecurityContract.PrivilegedHandlesDenied(5,5)); Require(!SecurityContract.PrivilegedHandlesDenied(5,0)); Require(!SecurityContract.PrivilegedHandlesDenied(0,5)); });
        Check("owned ACE removal preserves concurrent unrelated ACE", delegate {
            RawAcl acl=new RawAcl(2,0); CommonAce owned=SecurityContract.OwnedAce(new SecurityIdentifier("S-1-5-21-1-2-3-1001"),1);
            SecurityContract.AddOwnedAce(acl,owned);
            acl.InsertAce(0,SecurityContract.OwnedAce(new SecurityIdentifier("S-1-5-21-1-2-3-1002"),2));
            SecurityContract.RemoveOwnedAce(acl,owned); Require(acl.Count==1 && ((KnownAce)acl[0]).AccessMask==2);
        });
        Check("changed owned ACE blocks rollback without edits", delegate {
            RawAcl acl=new RawAcl(2,0); SecurityIdentifier sid=new SecurityIdentifier("S-1-5-21-1-2-3-1001");
            acl.InsertAce(0,SecurityContract.OwnedAce(sid,3));
            Reject("ace_changed_cleanup_blocked",delegate {SecurityContract.RemoveOwnedAce(acl,SecurityContract.OwnedAce(sid,1));}); Require(acl.Count==1);
        });
        Check("low integrity label requires exact no-write-up SID", delegate {
            Require(SecurityContract.IsLowNoWriteUp(new RawSecurityDescriptor("S:(ML;;NW;;;LW)")));
            Require(!SecurityContract.IsLowNoWriteUp(new RawSecurityDescriptor("S:(ML;;NW;;;ME)")));
            Require(!SecurityContract.IsLowNoWriteUp(new RawSecurityDescriptor("S:(ML;;NR;;;LW)")));
        });
        Check("native run stays disabled before ownership is verified", delegate {
            Reject("native_run_disabled_ownership_lifecycle_unverified",delegate {Contract.RequireNativeRunReady();});
        });
        Check("canary accepts only exact synthetic sibling paths", delegate {
            string run=@"C:\synthetic\.local-data\project-agent-work\codex-os-isolation-probe\run-0123456789abcdef0123456789abcdef";
            string executable=Path.Combine(run,"Canary.exe"), scratch=Path.Combine(run,"scratch.dat"), protectedFile=Path.Combine(run,"protected.dat");
            string shell=Path.Combine(Environment.SystemDirectory,"cmd.exe");
            Contract.SyntheticInputs(executable,scratch,protectedFile,shell);
            Reject("canary_input_out_of_scope",delegate {Contract.SyntheticInputs(executable,Path.Combine(run,"real.dat"),protectedFile,shell);});
            Reject("canary_input_out_of_scope",delegate {Contract.SyntheticInputs(executable,scratch,Path.Combine(run,"other.dat"),shell);});
            Reject("canary_input_out_of_scope",delegate {Contract.SyntheticInputs(executable,scratch,protectedFile,executable);});
        });
        Console.WriteLine("RESULT failures=" + failures); return failures==0 ? 0 : 1;
    }
}
}
