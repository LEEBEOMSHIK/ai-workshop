"""Fixed original-deployment collector for a trusted Windows/Docker operator.

These records are operator provenance, not authenticated per-invocation history.
Support assumes no endpoint overrides, copied cluster, manual host/guest writers,
privileged record edits or automation during maintenance. Unknowns fail closed.
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

import httpx
from dotenv import dotenv_values

from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.alias_recovery_local import (
    LocalRecoveryRefusal,
    ServerIdentity,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_wsl import (
    classify_infrastructure,
    command_tokens,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot

HISTORY_KIND = "trusted_operator_original_cutover_history_v1"
MODULE = "ai_workshop.labs.rag.indexing.alias_recovery_cli"
# The sole supported pre-existing topology, from the approved original inventory.
CONTAINER = "c890380a5e6f21beb7692c78594fac5aeb84baee22cb0f6e8ba421442b5e58d6"
PEERS = (
    "1124ac9fb6ecd23961caf688f289be1278205cfd98064de8e7a5f0734ca76e69",
    "64429df242c24b6506745908f0a1ea975243005aad2a3d13482caec46d1a3789",
    CONTAINER,
)
NETWORK = "9927bbc435db54d725f34656c7b6f27401d3dd070bc791c6792437f89930b93c"
DAEMON = "cb240d2c-c34d-4c20-9993-2c8a03cc167d"
CONTEXT_ENDPOINT_DIGEST = "30341252ca9aa2b298da11cd8527fdfbf8ab30a2f3b5a3c871188c778b20af30"
_ENV_SHA = "de253021f0074c161d71b2f1a9b50f921abd927e5ed5d27bee108a73c5a2d1a5"
_ES_HISTORY_SHA = "4f4d58e1290e2b2d2c6daf456ae1f34ea8cfc372ff581b376180e1ac9f8ab355"
_WORKLOG_SHA = "d80bf6ccf38c8d069bbbd84824f9ab718e71234fb3a510201b7fbd508cbb995a"
HISTORY_FILES = {
    ".local-data/backups/original-rag-cutover-20260920/original.env": _ENV_SHA,
    ".local-data/backups/original-rag-cutover-20260920/es-identities.json": _ES_HISTORY_SHA,
    "docs/worklogs/2026-09-20-original-environment-rag-cutover.md": _WORKLOG_SHA,
}
HISTORY_AT = datetime(2026, 9, 20, 13, 31, 32, 396164, tzinfo=UTC)
FRONTEND_LAUNCHER_AT = datetime(2026, 9, 29, 1, 4, 31, 21403, tzinfo=UTC)
NODE_SHA = "9a4eb5f1c29c6a2e93852ead46b999e284a6a5ca8bab4d4e241d587d025a52de"
DOCKER_EXE = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
ORIGINAL_IMAGE_ID = "sha256:80d3ab189f131fca45c958c281975078ac88d8b133200fbae33d70baa40f4654"
POWERSHELL_EXE = (
    r"C:\Program Files\WindowsApps\Microsoft.PowerShell_7.6.6.0_arm64__8wekyb3d8bbwe\pwsh.exe"
)
POWERSHELL_SHA = "abb215e4d87889c85a18333a310b1dbdae33e78a25e13dc7cf129fbdaea848e0"
WSL_EXE = r"C:\Windows\System32\wsl.exe"
NETSH_EXE = r"C:\Windows\System32\netsh.exe"

# Only fixed public refusal codes may cross preflight's native/CLI boundary.
# Future or caller-supplied diagnostics require explicit review before inclusion.
HOST_FAILURE_DIAGNOSTICS = frozenset(
    {
        "host_ancestor_reparse",
        "host_binary_reparse",
        "host_identity_unverified",
        "host_path_unverified",
        "host_open_failed",
        "host_signature_unverified",
        "host_hash_unverified",
        "host_binary_changed",
        "host_observation_failed",
    }
)
PREFLIGHT_SAFE_DIAGNOSTICS = (
    frozenset(
        {
            "preflight_identity_blocked",
            "preflight_history_blocked",
            "preflight_clients_blocked",
            "preflight_blocked",
            "preflight_capability_required",
            "preflight_command_denied",
            "local_command_failed",
            "local_enumeration_incomplete",
            "powershell_binary_unverified",
            "collector_controller_unverified",
            "direct_original_endpoint_required",
            "proxy_environment_unsupported",
            "docker_override_unsupported",
            "user_wsl_unsupported",
            "portproxy_unsupported",
            "frontend_listener_unverified",
            "process_lifetime_changed",
            "frontend_registry_unverified",
            "wsl_infrastructure_unverified",
            "unknown_client_process",
            "unknown_live_connection",
            "server_observation_failed",
            "cluster_changed",
            "windows_local_required",
            "docker_context_changed",
            "docker_daemon_changed",
            "server_identity_changed",
            "single_node_topology_unverified",
            "protected_mount_unverified",
            "unknown_network_peer",
            "unknown_running_container",
            "server_not_running",
            "cluster_node_changed",
            "original_history_unsupported",
            "original_history_changed",
            "collector_process_unverified",
            "collector_interpreter_unverified",
            "collector_launcher_unverified",
            "frontend_launcher_unverified",
            "inventory_helper_unverified",
            "infrastructure_lifetime_changed",
        }
    )
    | HOST_FAILURE_DIAGNOSTICS
)


def safe_preflight_diagnostic(diagnostic: object, fallback: str) -> str:
    if type(diagnostic) is str and diagnostic in PREFLIGHT_SAFE_DIAGNOSTICS:
        return diagnostic
    return fallback


# No caller interpolation. Raw process command lines never leave this adapter.
HOST_SCRIPT = r"""
$ErrorActionPreference='Stop'
$hostFailure=$null; $hostResult=$null
$directories=[Collections.Generic.Dictionary[string,object]]::new(
 [StringComparer]::OrdinalIgnoreCase)
$files=[Collections.Generic.List[object]]::new()
try {
# Native handles bind pathname signature checks to the protected file and prevent
# ancestor replacement. No observations or handles survive this HOST invocation.
if (-not ('AliasHostFile' -as [type])) {
 $null=Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;
public sealed class AliasHostRefusal : IOException {
 public string Diagnostic { get; private set; }
 public AliasHostRefusal(string diagnostic) : base("HOST refused") { Diagnostic=diagnostic; }
}
public static class AliasHostFile {
 [StructLayout(LayoutKind.Sequential)] struct Info {
  public uint Attributes, CreationLow, CreationHigh, AccessLow, AccessHigh,
   WriteLow, WriteHigh, Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
 }
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 static extern SafeFileHandle CreateFileW(string name, uint access, uint share,
  IntPtr security, uint disposition, uint flags, IntPtr template);
 [DllImport("kernel32.dll", SetLastError=true)]
 static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 static extern uint GetFinalPathNameByHandleW(SafeFileHandle handle, StringBuilder path,
  uint length, uint flags);
 [StructLayout(LayoutKind.Sequential)] struct TagInfo { public uint Attributes, Tag; }
 [DllImport("kernel32.dll", SetLastError=true)]
 static extern bool GetFileInformationByHandleEx(SafeFileHandle handle, int kind,
  out TagInfo info, uint size);
 public static void Refuse(string diagnostic) { throw new AliasHostRefusal(diagnostic); }
 public static string Identity(SafeFileHandle handle, string expected, bool ancestor=false) {
  Info info; var path=new StringBuilder(32768);
  uint size=GetFinalPathNameByHandleW(handle,path,(uint)path.Capacity,0);
  if(!GetFileInformationByHandle(handle,out info) || size==0 || size>=path.Capacity)
   throw new AliasHostRefusal("host_identity_unverified");
  if((info.Attributes & 0x400)!=0)
   throw new AliasHostRefusal(ancestor ? "host_ancestor_reparse" : "host_binary_reparse");
  if(!String.Equals(path.ToString(),@"\\?\"+expected,StringComparison.OrdinalIgnoreCase))
   throw new AliasHostRefusal("host_path_unverified");
  return info.Volume+":"+info.IndexHigh+":"+info.IndexLow;
 }
 public static SafeFileHandle Directory(string path) {
  var handle=CreateFileW(path,0,1,IntPtr.Zero,3,0x02200000,IntPtr.Zero);
  try {
   if(handle.IsInvalid) throw new AliasHostRefusal("host_open_failed");
   Identity(handle,path,true); return handle;
  } catch { handle.Dispose(); throw; }
 }
 public static SafeFileHandle NodeAliasDirectory() {
  const string expected=@"C:\nvm4w\nodejs";
  var handle=CreateFileW(expected,0,1,IntPtr.Zero,3,0x02200000,IntPtr.Zero);
  try {
   if(handle.IsInvalid) throw new AliasHostRefusal("host_open_failed");
   Info info; var path=new StringBuilder(32768);
   uint size=GetFinalPathNameByHandleW(handle,path,(uint)path.Capacity,0);
   if(!GetFileInformationByHandle(handle,out info) || size==0 || size>=path.Capacity)
    throw new AliasHostRefusal("host_identity_unverified");
   TagInfo tag;
   if(!GetFileInformationByHandleEx(handle,9,out tag,8) || tag.Tag!=0xA000000C ||
    (info.Attributes & 0x400)==0 ||
    !String.Equals(path.ToString(),@"\\?\"+expected,StringComparison.OrdinalIgnoreCase))
    throw new AliasHostRefusal("host_path_unverified");
   return handle;
  } catch { handle.Dispose(); throw; }
 }
 public static string NodePhysicalPath(SafeFileHandle handle) {
  Info info; var path=new StringBuilder(32768);
  uint size=GetFinalPathNameByHandleW(handle,path,(uint)path.Capacity,0);
  if(!GetFileInformationByHandle(handle,out info) || size==0 || size>=path.Capacity ||
   (info.Attributes & 0x400)!=0) throw new AliasHostRefusal("host_identity_unverified");
  string value=path.ToString();
  if(!value.StartsWith(@"\\?\") || value.Length<8)
   throw new AliasHostRefusal("host_path_unverified");
  value=value.Substring(4);
  if(value.Length<3 || !Char.IsLetter(value[0]) || value[1]!=':' || value[2]!='\\' ||
   value.IndexOf(':',2)>=0 ||
   !String.Equals(Path.GetFullPath(value),value,StringComparison.Ordinal) ||
   !String.Equals(Path.GetFileName(value),"node.exe",StringComparison.OrdinalIgnoreCase) ||
   !String.Equals(Path.GetFileName(Path.GetDirectoryName(value)),"v24.18.0",
   StringComparison.OrdinalIgnoreCase))
   throw new AliasHostRefusal("host_path_unverified");
  return value;
 }
}
'@
}
$binaryObservations=[Collections.Generic.Dictionary[string,object]]::new(
 [StringComparer]::OrdinalIgnoreCase)
$processes=@(Get-CimInstance Win32_Process | ForEach-Object {
 $signature=$null; $digest=$null
 if ($_.Name -match '^(node|wsl.*|com\.docker\..*)\.exe$' -and $_.ExecutablePath) {
  $path=$_.ExecutablePath.Replace('/','\')
  if($path -notmatch '^[A-Za-z]:\\' -or $path.Substring(2).Contains(':') -or
   [IO.Path]::GetFullPath($path) -cne $path){[AliasHostFile]::Refuse('host_path_unverified')}
  $aliasPath=$null
  if($_.Name -ieq 'node.exe' -and $path -ieq 'C:\nvm4w\nodejs\node.exe') {
   $aliasPath=$path
   $aliasAncestors=[Collections.Generic.List[string]]::new()
   $aliasParent=[IO.Path]::GetDirectoryName('C:\nvm4w\nodejs')
   while($aliasParent){$aliasAncestors.Insert(0,$aliasParent);$aliasParent=[IO.Path]::GetDirectoryName($aliasParent)}
   foreach($aliasParent in $aliasAncestors) {
    if(-not $directories.ContainsKey($aliasParent)) {
     $directories.Add($aliasParent,[AliasHostFile]::Directory($aliasParent))
    }
   }
   if(-not $directories.ContainsKey('C:\nvm4w\nodejs')) {
    $directories.Add('C:\nvm4w\nodejs',[AliasHostFile]::NodeAliasDirectory())
   }
   try {$aliasProbe=[IO.File]::Open($aliasPath,[IO.FileMode]::Open,
    [IO.FileAccess]::Read,[IO.FileShare]::Read)}
   catch {[AliasHostFile]::Refuse('host_open_failed')}
   $files.Add($aliasProbe)
   $path=[AliasHostFile]::NodePhysicalPath($aliasProbe.SafeFileHandle)
  }
  if(-not $binaryObservations.ContainsKey($path)) {
   $ancestors=[Collections.Generic.List[string]]::new()
   $directory=[IO.Path]::GetDirectoryName($path)
   while($directory){$ancestors.Insert(0,$directory);$directory=[IO.Path]::GetDirectoryName($directory)}
   foreach($directory in $ancestors) {
    if(-not $directories.ContainsKey($directory)) {
     $directories.Add($directory,[AliasHostFile]::Directory($directory))
    }
   }
   try {$file=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)}
   catch {[AliasHostFile]::Refuse('host_open_failed')}
   $files.Add($file)
   $identity=[AliasHostFile]::Identity($file.SafeFileHandle,$path)
   if($aliasPath) {
    if([AliasHostFile]::Identity($aliasProbe.SafeFileHandle,$path) -ne $identity){
     [AliasHostFile]::Refuse('host_binary_changed')
    }
   }
   try {$signature=Get-AuthenticodeSignature -LiteralPath $path}
   catch {[AliasHostFile]::Refuse('host_signature_unverified')}
   if(-not $signature -or [string]$signature.Status -ne 'Valid' -or
    -not $signature.SignerCertificate){[AliasHostFile]::Refuse('host_signature_unverified')}
   # Pathname APIs must still resolve to the exact protected file object.
   try {
    $probe=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
   }
   catch {[AliasHostFile]::Refuse('host_open_failed')}
   $files.Add($probe)
   try {
    if([AliasHostFile]::Identity($probe.SafeFileHandle,$path) -ne $identity){
     [AliasHostFile]::Refuse('host_binary_changed')
    }
   }
   finally {$probe.Dispose()}
   try {$digest=(Get-FileHash -Algorithm SHA256 -InputStream $file).Hash.ToLowerInvariant()}
   catch {[AliasHostFile]::Refuse('host_hash_unverified')}
   if($digest -notmatch '^[0-9a-f]{64}$'){[AliasHostFile]::Refuse('host_hash_unverified')}
   if($aliasPath -and
    $digest -ne '9a4eb5f1c29c6a2e93852ead46b999e284a6a5ca8bab4d4e241d587d025a52de'){
    [AliasHostFile]::Refuse('host_binary_changed')
   }
   $binaryObservations.Add($path,[PSCustomObject]@{signature=$signature;digest=$digest})
  }
  $signature=$binaryObservations[$path].signature
  $digest=$binaryObservations[$path].digest
 }
 [PSCustomObject]@{pid=[int]$_.ProcessId;parent_pid=[int]$_.ParentProcessId;
  created_at=([DateTimeOffset]$_.CreationDate).ToUniversalTime().ToString('o');
  name=$_.Name;command=$_.CommandLine;executable=$_.ExecutablePath;
  signature_status=$(if($signature){[string]$signature.Status}else{''});
  signer=$(if($signature -and $signature.SignerCertificate){
   $signature.SignerCertificate.Subject
  }else{''});
  binary_sha256=$digest}
})
$tcp=@(Get-NetTCPConnection | Where-Object {
 $_.LocalPort -eq 9200 -or $_.RemotePort -eq 9200 -or
 ($_.LocalPort -eq 18000 -and $_.State -eq 'Listen')
} | ForEach-Object {[PSCustomObject]@{pid=[int]$_.OwningProcess;state=[string]$_.State;
 local_port=[int]$_.LocalPort;remote_port=[int]$_.RemotePort;
 local_address=$_.LocalAddress;remote_address=$_.RemoteAddress}})
$frontend=@(Get-NetTCPConnection | Where-Object {$_.LocalPort -eq 5173 -and $_.State -eq 'Listen'} |
 ForEach-Object {[PSCustomObject]@{pid=[int]$_.OwningProcess;state=[string]$_.State;
 local_port=[int]$_.LocalPort;local_address=$_.LocalAddress}})
$hostResult=[PSCustomObject]@{processes=$processes;tcp=$tcp;frontend_tcp=$frontend;helper_pid=$PID}
} catch {
 $hostFailure='host_observation_failed'
 $cause=$_.Exception
 if($cause -is [Management.Automation.MethodInvocationException]){$cause=$cause.InnerException}
 $refusalType='AliasHostRefusal' -as [type]
 if($refusalType -and $refusalType.IsInstanceOfType($cause) -and $cause.Diagnostic -in @(
  'host_ancestor_reparse','host_binary_reparse','host_identity_unverified',
  'host_path_unverified','host_open_failed','host_signature_unverified',
  'host_hash_unverified','host_binary_changed','host_observation_failed')) {
  $hostFailure=$cause.Diagnostic
 }
} finally {
 foreach($file in $files){try{$file.Dispose()}catch{$hostFailure='host_observation_failed'}}
 foreach($directory in $directories.Values){
  try{$directory.Dispose()}catch{$hostFailure='host_observation_failed'}
 }
}
if($hostFailure){
 [PSCustomObject]@{diagnostic=$hostFailure}|ConvertTo-Json -Compress
 exit 1
}
$hostResult|ConvertTo-Json -Depth 6 -Compress
"""

WSL_STATE_SCRIPT = r"""
$ErrorActionPreference='Stop'
$service=Get-CimInstance Win32_Service -Filter "Name = 'WSLService'"
if ($null -eq $service) {throw 'Required service unavailable'}
$binaryPath=$service.PathName.Trim('"')
$signature=Get-AuthenticodeSignature -LiteralPath $binaryPath
$digest=(Get-FileHash -Algorithm SHA256 -LiteralPath $binaryPath).Hash.ToLowerInvariant()
$distros=@(Get-ChildItem -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' |
 ForEach-Object { $record=Get-ItemProperty -LiteralPath $_.PSPath
  if ($record.DistributionName -eq 'docker-desktop') {
   [PSCustomObject]@{name=$record.DistributionName;id=$_.PSChildName}
  }
 })
[PSCustomObject]@{docker_distros=$distros;service=[PSCustomObject]@{
 name=$service.Name;state=$service.State;start_name=$service.StartName;
 pid=[int]$service.ProcessId;path=$binaryPath;binary_sha256=$digest;
 signature_status=[string]$signature.Status;signer=$signature.SignerCertificate.Subject
}}|ConvertTo-Json -Depth 5 -Compress
"""


class FixedCommand(StrEnum):
    CONTEXT = "context"
    DAEMON = "daemon"
    CONTAINER = "container"
    IMAGE_METADATA = "image_metadata"
    ORIGINAL_DAEMON_ID = "original_daemon_id"
    ORIGINAL_STOP_METADATA = "original_stop_metadata"
    ORIGINAL_ALL_IDS = "original_all_ids"
    ORIGINAL_SLOT_INVENTORY = "original_slot_inventory"
    SELECTED_SLOT_CONTAINER = "selected_slot_container"
    SELECTED_IMAGE_RAW = "selected_image_raw"
    SELECTED_VOLUME_RAW = "selected_volume_raw"
    SELECTED_NETWORK_RAW = "selected_network_raw"
    SELECTED_SECURITY_CONFIG = "selected_security_config"
    ORIGINAL_VOLUME_METADATA = "original_volume_metadata"
    NETWORK = "network"
    RUNNING = "running"
    PEERS = "peers"
    HOST = "host"
    WSL_STATE = "wsl_state"
    WSL = "wsl"
    PORTPROXY = "portproxy"
    STOP = "stop"
    START = "start"


def command_argv(command: FixedCommand) -> tuple[str, ...]:
    docker = (DOCKER_EXE, "--context", "desktop-linux")
    original = (DOCKER_EXE, "--host", "npipe:////./pipe/dockerDesktopLinuxEngine")
    return {
        FixedCommand.CONTEXT: (DOCKER_EXE, "context", "inspect", "desktop-linux"),
        FixedCommand.DAEMON: (*docker, "info", "--format", "{{json .}}"),
        FixedCommand.CONTAINER: (*docker, "inspect", CONTAINER),
        FixedCommand.IMAGE_METADATA: (
            DOCKER_EXE,
            "--host",
            "npipe:////./pipe/dockerDesktopLinuxEngine",
            "image",
            "inspect",
            ORIGINAL_IMAGE_ID,
            "--format",
            '{"image_id":{{json .Id}},"repo_digests":{{json .RepoDigests}},'
            '"os":{{json .Os}},"architecture":{{json .Architecture}}}',
        ),
        FixedCommand.ORIGINAL_DAEMON_ID: (
            *original,
            "info",
            "--format",
            '{"id":{{json .ID}},"os":{{json .OSType}}}',
        ),
        FixedCommand.ORIGINAL_STOP_METADATA: (
            *original,
            "inspect",
            CONTAINER,
            "--format",
            '{"container_id":{{json .Id}},"image_id":{{json .Image}},'
            '"running":{{json .State.Running}},"restarting":{{json .State.Restarting}},'
            '"dead":{{json .State.Dead}},"pid":{{json .State.Pid}},'
            '"started_at":{{json .State.StartedAt}},"finished_at":{{json .State.FinishedAt}}}',
        ),
        FixedCommand.ORIGINAL_ALL_IDS: (
            *original,
            "ps",
            "--all",
            "--no-trunc",
            "--format",
            "{{.ID}}",
        ),
        FixedCommand.ORIGINAL_SLOT_INVENTORY: (
            *original,
            "ps",
            "--all",
            "--no-trunc",
            "--format",
            '{"ID":{{json .ID}},"Names":{{json .Names}},"Labels":{{json .Labels}}}',
        ),
        FixedCommand.SELECTED_SLOT_CONTAINER: (
            *original,
            "inspect",
            "--type",
            "container",
            "ai-workshop-elasticsearch-1",
        ),
        FixedCommand.SELECTED_IMAGE_RAW: (*original, "image", "inspect", ORIGINAL_IMAGE_ID),
        FixedCommand.SELECTED_VOLUME_RAW: (
            *original,
            "volume",
            "inspect",
            "ai-workshop_elasticsearch-data",
        ),
        FixedCommand.SELECTED_NETWORK_RAW: (*original, "network", "inspect", NETWORK),
        FixedCommand.SELECTED_SECURITY_CONFIG: (
            *original,
            "exec",
            "ai-workshop-elasticsearch-1",
            "/usr/bin/cat",
            "/usr/share/elasticsearch/config/elasticsearch.yml",
        ),
        FixedCommand.ORIGINAL_VOLUME_METADATA: (
            *original,
            "volume",
            "inspect",
            "ai-workshop_elasticsearch-data",
            "--format",
            '{"name":{{json .Name}},"driver":{{json .Driver}},"scope":{{json .Scope}},'
            '"created_at":{{json .CreatedAt}},"mountpoint":{{json .Mountpoint}},'
            '"options":{{json .Options}}}',
        ),
        FixedCommand.NETWORK: (*docker, "network", "inspect", NETWORK),
        FixedCommand.RUNNING: (*docker, "ps", "--no-trunc", "--format", "{{.ID}}"),
        FixedCommand.PEERS: (*docker, "inspect", *PEERS[:2]),
        FixedCommand.HOST: (
            POWERSHELL_EXE,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(HOST_SCRIPT.encode("utf-16le")).decode(),
        ),
        FixedCommand.WSL: (WSL_EXE, "--list", "--running", "--quiet"),
        FixedCommand.WSL_STATE: (
            POWERSHELL_EXE,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            base64.b64encode(WSL_STATE_SCRIPT.encode("utf-16le")).decode(),
        ),
        FixedCommand.PORTPROXY: (NETSH_EXE, "interface", "portproxy", "show", "all"),
        FixedCommand.STOP: (*docker, "stop", "--time", "30", CONTAINER),
        FixedCommand.START: (*docker, "start", CONTAINER),
    }[command]


class CommandExecutor(Protocol):
    async def run(self, command: FixedCommand) -> str: ...


class ReadOnlyCommandExecutor:
    """Positive fixed-command capability; strings and future commands fail closed."""

    _commands = frozenset(
        {
            FixedCommand.CONTEXT,
            FixedCommand.DAEMON,
            FixedCommand.CONTAINER,
            FixedCommand.IMAGE_METADATA,
            FixedCommand.ORIGINAL_DAEMON_ID,
            FixedCommand.ORIGINAL_STOP_METADATA,
            FixedCommand.ORIGINAL_ALL_IDS,
            FixedCommand.ORIGINAL_SLOT_INVENTORY,
            FixedCommand.SELECTED_SLOT_CONTAINER,
            FixedCommand.SELECTED_IMAGE_RAW,
            FixedCommand.SELECTED_VOLUME_RAW,
            FixedCommand.SELECTED_NETWORK_RAW,
            FixedCommand.SELECTED_SECURITY_CONFIG,
            FixedCommand.ORIGINAL_VOLUME_METADATA,
            FixedCommand.NETWORK,
            FixedCommand.RUNNING,
            FixedCommand.PEERS,
            FixedCommand.HOST,
            FixedCommand.WSL_STATE,
            FixedCommand.WSL,
            FixedCommand.PORTPROXY,
        }
    )

    def __init__(self, delegate: CommandExecutor) -> None:
        self.delegate = delegate

    async def run(self, command: FixedCommand) -> str:
        if not isinstance(command, FixedCommand) or command not in self._commands:
            raise LocalRecoveryRefusal("preflight_command_denied")
        return await self.delegate.run(command)


class NativeCommandExecutor:
    async def run(self, command: FixedCommand) -> str:
        try:
            argv = command_argv(command)
            if command in {FixedCommand.HOST, FixedCommand.WSL_STATE}:
                _verify_powershell(argv[0])
            result = await asyncio.to_thread(
                subprocess.run,
                argv,
                shell=False,
                check=False,
                capture_output=True,
                timeout=45,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                if command is FixedCommand.HOST and len(result.stdout) <= 256:
                    # Tuples retain every object pair, so duplicate keys cannot collapse.
                    payload = json.loads(result.stdout.decode("utf-8"), object_pairs_hook=tuple)
                    if (
                        isinstance(payload, tuple)
                        and len(payload) == 1
                        and payload[0][0] == "diagnostic"
                        and type(payload[0][1]) is str
                        and payload[0][1] in HOST_FAILURE_DIAGNOSTICS
                    ):
                        raise LocalRecoveryRefusal(payload[0][1])
                raise LocalRecoveryRefusal("local_command_failed")
            if len(result.stdout) > 4_194_304:
                raise LocalRecoveryRefusal("local_command_failed")
            encoding = "utf-16le" if command == FixedCommand.WSL else "utf-8-sig"
            return result.stdout.decode(encoding, errors="strict").strip()
        except LocalRecoveryRefusal:
            raise
        except Exception:
            raise LocalRecoveryRefusal("local_command_failed") from None


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _obj(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise LocalRecoveryRefusal("local_enumeration_incomplete")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise LocalRecoveryRefusal("local_enumeration_incomplete")
    return value


def _str(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise LocalRecoveryRefusal("local_enumeration_incomplete")
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise LocalRecoveryRefusal("local_enumeration_incomplete")
    return value


def _at(value: object) -> datetime:
    try:
        result = datetime.fromisoformat(_str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except Exception:
        raise LocalRecoveryRefusal("local_enumeration_incomplete") from None


def _path(value: str) -> str:
    return value.replace("\\", "/").lower().rstrip("/")


def _verify_powershell(executable: str) -> None:
    try:
        path = Path(executable)
        if (
            _path(executable) != _path(POWERSHELL_EXE)
            or path.is_symlink()
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != POWERSHELL_SHA
        ):
            raise ValueError
    except Exception:
        raise LocalRecoveryRefusal("powershell_binary_unverified") from None


def controller_payload(root: Path, argv: tuple[str, ...]) -> str:
    """The sole supported compound controller, with exact current CLI argv."""
    executable = root / "backend/.venv/Scripts/python.exe"
    if _path(argv[0]) != _path(str(executable)) or argv[1:3] != ("-m", MODULE):
        raise LocalRecoveryRefusal("collector_controller_unverified")
    if any(re.fullmatch(r"[A-Za-z0-9_.-]+", arg) is None for arg in argv[1:]):
        raise LocalRecoveryRefusal("collector_controller_unverified")
    root_text = str(root).replace("'", "''")
    executable_text = str(executable).replace("'", "''")
    return (
        "$aliasRecoveryKeys = @([Environment]::GetEnvironmentVariables('Process').Keys | "
        "Where-Object { $_ -like 'AI_WORKSHOP_*' })\n"
        "foreach ($aliasRecoveryKey in $aliasRecoveryKeys) { "
        "[Environment]::SetEnvironmentVariable($aliasRecoveryKey, $null, 'Process') }\n"
        f"Set-Location -LiteralPath '{root_text}'\n"
        f"& '{executable_text}' " + " ".join(argv[1:])
    )


def _controller_matches(command: str, executable: str, payloads: set[str]) -> bool:
    if _path(executable) != _path(POWERSHELL_EXE):
        return False
    framing = re.search(r"\s-(Command|EncodedCommand)\s+", command, re.IGNORECASE)
    if framing is None:
        return False
    try:
        prefix = command_tokens(command[: framing.start()])
        if _path(prefix[0]) != _path(executable) or any(
            flag.lower() not in {"-nologo", "-noprofile", "-noninteractive"} for flag in prefix[1:]
        ):
            return False
        _verify_powershell(executable)
        payload = command[framing.end() :].strip()
        if framing.group(1).lower() == "encodedcommand":
            if len(payload) > 131072:
                return False
            payload = base64.b64decode(payload, validate=True).decode("utf-16le")
        elif payload.startswith('"') and payload.endswith('"'):
            payload = payload[1:-1]
        return payload.replace("\r\n", "\n").strip() in payloads
    except Exception:
        return False


def validate_endpoint(url: str, environment: Mapping[str, str]) -> None:
    if url != "http://127.0.0.1:9200":
        raise LocalRecoveryRefusal("direct_original_endpoint_required")
    if any("proxy" in key.lower() and value for key, value in environment.items()):
        raise LocalRecoveryRefusal("proxy_environment_unsupported")
    if any(key.upper().startswith("DOCKER_") and value for key, value in environment.items()):
        raise LocalRecoveryRefusal("docker_override_unsupported")


@dataclass(frozen=True, slots=True)
class ProcessLifetime:
    pid: int
    parent_pid: int
    created_at: datetime
    name: str
    command: str
    executable: str

    @classmethod
    def from_observation(cls, value: object) -> "ProcessLifetime":
        process = _obj(value)
        return cls(
            _int(process.get("pid")),
            _int(process.get("parent_pid")),
            _at(process.get("created_at")),
            _str(process.get("name")).lower(),
            _str(process.get("command")),
            _path(_str(process.get("executable"))),
        )


def validate_host(data: object, allowed: tuple[ProcessLifetime, ...]) -> str:
    host = _obj(data)
    distros = {_str(item) for item in _list(host.get("distros"))}
    if distros != {"docker-desktop"}:
        raise LocalRecoveryRefusal("user_wsl_unsupported")
    portproxy = host.get("portproxy")
    if not isinstance(portproxy, str):
        raise LocalRecoveryRefusal("local_enumeration_incomplete")
    # Address-family independent: four-column address/port/address/port rows.
    if any(re.fullmatch(r"\S+\s+\d+\s+\S+\s+\d+", line.strip()) for line in portproxy.splitlines()):
        raise LocalRecoveryRefusal("portproxy_unsupported")
    processes = [_obj(item) for item in _list(host.get("processes"))]
    infrastructure = classify_infrastructure(processes, _obj(host.get("wsl_state", {})))
    by_pid = {_int(item.get("pid")): item for item in processes}
    if len(by_pid) != len(processes):
        raise LocalRecoveryRefusal("local_enumeration_incomplete")
    allowed_pids = {item.pid: item for item in allowed}
    frontend_pids = {
        p.pid
        for p in allowed
        if p.name == "node.exe" and "/next/dist/server/lib/start-server.js" in _path(p.command)
    }
    frontend_rows = [_obj(item) for item in _list(host.get("frontend_tcp", []))]
    if frontend_pids:
        if len(frontend_rows) != 1 or frontend_rows[0] != {
            "pid": next(iter(frontend_pids)),
            "state": "Listen",
            "local_port": 5173,
            "local_address": "127.0.0.1",
        }:
            raise LocalRecoveryRefusal("frontend_listener_unverified")
    elif frontend_rows:
        raise LocalRecoveryRefusal("frontend_listener_unverified")
    safe_facts: list[object] = []
    docker_listeners = infrastructure.docker_listener_pids
    for process in processes:
        pid = _int(process.get("pid"))
        name = _str(process.get("name")).lower()
        if pid in allowed_pids:
            if ProcessLifetime.from_observation(process) != allowed_pids[pid]:
                raise LocalRecoveryRefusal("process_lifetime_changed")
            if name == "node.exe" and (
                process.get("binary_sha256") != NODE_SHA
                or process.get("signature_status") != "Valid"
            ):
                raise LocalRecoveryRefusal("frontend_registry_unverified")
            safe_facts.append(
                [pid, allowed_pids[pid].created_at.isoformat(), "exact_collector_or_frontend"]
            )
            continue
        command = process.get("command")
        command_text = command.lower() if isinstance(command, str) else ""
        if name.startswith(("wsl", "com.docker.")):
            if pid not in infrastructure.allowed_pids:
                raise LocalRecoveryRefusal("wsl_infrastructure_unverified")
            safe_facts.append(
                [pid, _str(process.get("created_at")), "signed_docker_infrastructure"]
            )
            continue
        if (
            name.startswith(("python", "pypy", "node", "ruby", "java"))
            or name in {"ssh.exe", "plink.exe", "ngrok.exe", "cloudflared.exe", "socat.exe"}
            or any(
                token in command_text
                for token in ("ai_workshop", "ai-workshop", "celery", "uvicorn", "9200")
            )
            or (name in {"powershell.exe", "pwsh.exe", "cmd.exe"} and not command_text)
        ):
            raise LocalRecoveryRefusal("unknown_client_process")
    for connection in _list(host.get("tcp")):
        row = _obj(connection)
        pid, state = _int(row.get("pid")), _str(row.get("state"))
        if state == "TimeWait" and pid == 0:
            continue
        if (
            state == "Listen"
            and _int(row.get("local_port")) == 9200
            and row.get("local_address") == "127.0.0.1"
            and pid in docker_listeners
        ):
            safe_facts.append([pid, "direct_docker_listener"])
            continue
        raise LocalRecoveryRefusal("unknown_live_connection")
    return _digest([infrastructure.sha256, sorted(safe_facts, key=str)])


class DirectElasticsearchReader:
    """Literal local address, redirects disabled, no ambient proxies."""

    async def read(self, path: str) -> object:
        if path not in {
            "/",
            "/_cluster/health",
            "/_cluster/state/master_node,nodes",
            "/_nodes/jvm",
            "/_cat/indices/.security*?expand_wildcards=all&format=json&h=index",
        }:
            raise LocalRecoveryRefusal("direct_original_endpoint_required")
        try:
            async with httpx.AsyncClient(
                trust_env=False, follow_redirects=False, timeout=10
            ) as client:
                response = await client.get("http://127.0.0.1:9200" + path)
                if response.status_code != 200 or len(response.content) > 1_048_576:
                    raise LocalRecoveryRefusal("server_observation_failed")
                return cast(object, response.json())
        except LocalRecoveryRefusal:
            raise
        except Exception:
            raise LocalRecoveryRefusal("server_observation_failed") from None


class ElasticsearchReader(Protocol):
    async def read(self, path: str) -> object: ...


class OriginalWindowsBackend:
    def __init__(
        self,
        settings: Settings,
        root: Path,
        executor: CommandExecutor | None = None,
        reader: ElasticsearchReader | None = None,
    ) -> None:
        self.settings, self.root = settings, root.resolve()
        self.executor = executor or NativeCommandExecutor()
        self.reader = reader or DirectElasticsearchReader()
        self._allowed: tuple[ProcessLifetime, ...] | None = None
        self._infrastructure_sha256: str | None = None

    async def preflight(self, snapshot: AliasOperationSnapshot) -> None:
        # A fresh adapter avoids carrying observation state into recovery or another preflight.
        readonly = OriginalWindowsBackend(
            self.settings,
            self.root,
            ReadOnlyCommandExecutor(self.executor),
            self.reader,
        )
        try:
            identity = await readonly.identity()
            if identity.cluster_uuid != snapshot.cluster_uuid:
                raise LocalRecoveryRefusal("cluster_changed")
        except LocalRecoveryRefusal as exc:
            raise LocalRecoveryRefusal(
                safe_preflight_diagnostic(exc.diagnostic, "preflight_identity_blocked")
            ) from None
        except Exception:
            raise LocalRecoveryRefusal("preflight_identity_blocked") from None
        try:
            await readonly.history(snapshot, identity)
        except LocalRecoveryRefusal as exc:
            raise LocalRecoveryRefusal(
                safe_preflight_diagnostic(exc.diagnostic, "preflight_history_blocked")
            ) from None
        except Exception:
            raise LocalRecoveryRefusal("preflight_history_blocked") from None
        try:
            await readonly.clients_absent()
        except LocalRecoveryRefusal as exc:
            raise LocalRecoveryRefusal(
                safe_preflight_diagnostic(exc.diagnostic, "preflight_clients_blocked")
            ) from None
        except Exception:
            raise LocalRecoveryRefusal("preflight_clients_blocked") from None

    def _local(self) -> None:
        if self.settings.environment != "local" or sys.platform != "win32":
            raise LocalRecoveryRefusal("windows_local_required")
        validate_endpoint(self.settings.elasticsearch_url, os.environ)

    async def _json(self, command: FixedCommand) -> object:
        try:
            return cast(object, json.loads(await self.executor.run(command)))
        except LocalRecoveryRefusal:
            raise
        except Exception:
            raise LocalRecoveryRefusal("local_enumeration_incomplete") from None

    async def _container(self) -> tuple[dict[str, object], str, str]:
        self._local()
        contexts = _list(await self._json(FixedCommand.CONTEXT))
        if len(contexts) != 1:
            raise LocalRecoveryRefusal("docker_context_changed")
        context = _obj(contexts[0])
        endpoint = _str(_obj(_obj(context.get("Endpoints")).get("docker")).get("Host"))
        if (
            context.get("Name") != "desktop-linux"
            or not endpoint.startswith("npipe://")
            or hashlib.sha256(endpoint.encode()).hexdigest() != CONTEXT_ENDPOINT_DIGEST
        ):
            raise LocalRecoveryRefusal("docker_context_changed")
        daemon = _obj(await self._json(FixedCommand.DAEMON))
        if daemon.get("ID") != DAEMON or daemon.get("OSType") != "linux":
            raise LocalRecoveryRefusal("docker_daemon_changed")
        containers = _list(await self._json(FixedCommand.CONTAINER))
        if len(containers) != 1:
            raise LocalRecoveryRefusal("server_identity_changed")
        container = _obj(containers[0])
        config, host = _obj(container.get("Config")), _obj(container.get("HostConfig"))
        if (
            container.get("Id") != CONTAINER
            or "discovery.type=single-node" not in _list(config.get("Env"))
            or host.get("PortBindings")
            != {"9200/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9200"}]}
            or host.get("AutoRemove") is not False
            or host.get("Privileged") is not False
            or _obj(container.get("State")).get("Restarting") is not False
        ):
            raise LocalRecoveryRefusal("single_node_topology_unverified")
        mounts = _list(container.get("Mounts"))
        if len(mounts) != 1:
            raise LocalRecoveryRefusal("protected_mount_unverified")
        mount = _obj(mounts[0])
        if (
            mount.get("Type") != "volume"
            or mount.get("Destination") != "/usr/share/elasticsearch/data"
            or mount.get("RW") is not True
            or mount.get("Driver") != "local"
        ):
            raise LocalRecoveryRefusal("protected_mount_unverified")
        _str(mount.get("Name"))
        networks = _obj(_obj(container.get("NetworkSettings")).get("Networks"))
        if len(networks) != 1 or _obj(next(iter(networks.values()))).get("NetworkID") != NETWORK:
            raise LocalRecoveryRefusal("unknown_network_peer")
        network_list = _list(await self._json(FixedCommand.NETWORK))
        expected_peers = set(PEERS if _obj(container.get("State")).get("Running") else PEERS[:2])
        if (
            len(network_list) != 1
            or set(_obj(_obj(network_list[0]).get("Containers"))) != expected_peers
        ):
            raise LocalRecoveryRefusal("unknown_network_peer")
        if set((await self.executor.run(FixedCommand.RUNNING)).splitlines()) - set(PEERS):
            raise LocalRecoveryRefusal("unknown_running_container")
        peer_list = _list(await self._json(FixedCommand.PEERS))
        if len(peer_list) != 2:
            raise LocalRecoveryRefusal("unknown_network_peer")
        for peer, peer_id, service in zip(peer_list, PEERS[:2], ("redis", "postgres"), strict=True):
            p = _obj(peer)
            labels = _obj(_obj(p.get("Config")).get("Labels"))
            if (
                p.get("Id") != peer_id
                or labels.get("com.docker.compose.project") != "ai-workshop"
                or labels.get("com.docker.compose.service") != service
            ):
                raise LocalRecoveryRefusal("unknown_network_peer")
        return (
            container,
            _digest(mounts),
            _digest(
                {
                    "config": config,
                    "host": host,
                    "image": container.get("Image"),
                    "created_at": container.get("Created"),
                    "network_id": NETWORK,
                }
            ),
        )

    async def identity(self) -> ServerIdentity:
        container, mount_sha, config_sha = await self._container()
        state = _obj(container.get("State"))
        if state.get("Running") is not True:
            raise LocalRecoveryRefusal("server_not_running")
        root = _obj(await self.reader.read("/"))
        health = _obj(await self.reader.read("/_cluster/health"))
        cluster = _obj(await self.reader.read("/_cluster/state/master_node,nodes"))
        jvm = _obj(await self.reader.read("/_nodes/jvm"))
        nodes, jvm_nodes = _obj(cluster.get("nodes")), _obj(jvm.get("nodes"))
        if (
            len(nodes) != 1
            or set(nodes) != set(jvm_nodes)
            or health.get("number_of_nodes") != 1
            or health.get("number_of_data_nodes") != 1
            or health.get("status") not in {"yellow", "green"}
            or _obj(jvm.get("_nodes")) != {"total": 1, "successful": 1, "failed": 0}
        ):
            raise LocalRecoveryRefusal("single_node_topology_unverified")
        node = next(iter(nodes))
        if (
            cluster.get("master_node") != node
            or cluster.get("cluster_uuid") != root.get("cluster_uuid")
            or root.get("cluster_uuid") != self.settings.rag_index_cluster_uuid
        ):
            raise LocalRecoveryRefusal("cluster_node_changed")
        started_ms = _int(_obj(_obj(jvm_nodes[node]).get("jvm")).get("start_time_in_millis"))
        return ServerIdentity(
            "desktop-linux",
            DAEMON,
            CONTAINER,
            mount_sha,
            config_sha,
            _str(root.get("cluster_uuid")),
            node,
            _str(_obj(nodes[node]).get("ephemeral_id")),
            datetime.fromtimestamp(started_ms / 1000, UTC),
            _at(container.get("Created")),
            _at(state.get("StartedAt")),
            _at(state.get("FinishedAt")),
            True,
        )

    async def history(self, snapshot: AliasOperationSnapshot, identity: ServerIdentity) -> str:
        try:
            self._local()
            if (
                snapshot.store_id != self.settings.rag_index_store_id
                or snapshot.cluster_uuid != identity.cluster_uuid
                or not identity.created_at < HISTORY_AT < snapshot.created_at
            ):
                raise LocalRecoveryRefusal("original_history_unsupported")
            for name, digest in HISTORY_FILES.items():
                path = self.root / name
                if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise LocalRecoveryRefusal("original_history_changed")
            env_path = self.root / next(iter(HISTORY_FILES))
            origin = dotenv_values(env_path, interpolate=False)
            if origin.get("AI_WORKSHOP_ENVIRONMENT") != "local" or any(
                "proxy" in key.lower() for key in origin
            ):
                raise LocalRecoveryRefusal("original_history_unsupported")
            validate_endpoint(origin.get("AI_WORKSHOP_ELASTICSEARCH_URL") or "", {})
            identity_path = self.root / list(HISTORY_FILES)[1]
            historical = _obj(json.loads(identity_path.read_text(encoding="utf-8-sig")))
            if historical.get("cluster_uuid") != snapshot.cluster_uuid:
                raise LocalRecoveryRefusal("original_history_unsupported")
            return _digest(
                {
                    "source": HISTORY_KIND,
                    "files": HISTORY_FILES,
                    "observed_at": HISTORY_AT.isoformat(),
                    "container": identity.container_id,
                    "created_at": identity.created_at.isoformat(),
                    "mount": identity.mount_sha256,
                    "config": identity.config_sha256,
                    "store": snapshot.store_id,
                    "cluster": snapshot.cluster_uuid,
                }
            )
        except LocalRecoveryRefusal:
            raise
        except Exception:
            raise LocalRecoveryRefusal("original_history_unsupported") from None

    def _initial_allowed(self, host: dict[str, object]) -> tuple[ProcessLifetime, ...]:
        processes = [_obj(item) for item in _list(host.get("processes"))]
        by_pid = {_int(item.get("pid")): item for item in processes}
        own = ProcessLifetime.from_observation(by_pid.get(os.getpid()))
        expected = tuple(_path(value.strip('"')) for value in sys.orig_argv)

        def cli_process(p: ProcessLifetime) -> bool:
            tokens = tuple(_path(value) for value in command_tokens(p.command))
            return tokens == expected and f"-m {MODULE}" in p.command and p.name == "python.exe"

        if not cli_process(own):
            raise LocalRecoveryRefusal("collector_process_unverified")
        interpreters = {
            _path(str(self.root / "backend/.venv/Scripts/python.exe")),
            _path(str(Path(_str(getattr(sys, "_base_executable", sys.executable))).resolve())),
        }
        if own.executable not in interpreters:
            raise LocalRecoveryRefusal("collector_interpreter_unverified")
        allowed = [own]
        parent_raw = by_pid.get(own.parent_pid)
        if parent_raw is not None:
            parent = ProcessLifetime.from_observation(parent_raw)
            if cli_process(parent):
                # Exact venv launcher only; no arbitrary descendants or other Python.
                if parent.executable != _path(str(self.root / "backend/.venv/Scripts/python.exe")):
                    raise LocalRecoveryRefusal("collector_launcher_unverified")
                allowed.append(parent)
                parent_raw = by_pid.get(parent.parent_pid)
            if parent_raw is not None:
                controller = ProcessLifetime.from_observation(parent_raw)
                # Exact direct/fixed payloads support plain or encoded PowerShell framing.
                # Script files and arbitrary compound supervisor tails are unsupported.
                invocation = subprocess.list2cmdline(sys.orig_argv)
                payloads = {
                    invocation,
                    "& " + invocation,
                    controller_payload(self.root, tuple(sys.orig_argv)),
                }
                if controller.name in {"powershell.exe", "pwsh.exe"}:
                    if not _controller_matches(controller.command, controller.executable, payloads):
                        raise LocalRecoveryRefusal("collector_controller_unverified")
                    allowed.append(controller)
        # Fixed original registry. A frontend exception is exact PID/time/module/binary.
        registry = _list(
            json.loads(
                (self.root / ".local-data/dev-logs/original-rag-processes.json").read_text(
                    encoding="utf-8-sig"
                )
            )
        )
        frontend = [_obj(row) for row in registry if _obj(row).get("phase") == "frontend"]
        if len(frontend) != 1:
            raise LocalRecoveryRefusal("frontend_registry_unverified")
        registered = frontend[0]
        pid = _int(registered.get("pid"))
        raw_frontend = by_pid.get(pid)
        if raw_frontend is not None:
            child = ProcessLifetime.from_observation(raw_frontend)
            child_arguments = command_tokens(child.command)
            module = self.root / "frontend/node_modules/next/dist/server/lib/start-server.js"
            actual_module = (
                Path(child_arguments[1]).resolve(strict=True) if len(child_arguments) == 2 else None
            )
            expected_module = module.resolve(strict=True)
            if (
                child.created_at != _at(registered.get("started_at"))
                or child.name != "node.exe"
                or len(child_arguments) != 2
                or _path(child_arguments[0]) != child.executable
                or actual_module != expected_module
                or not expected_module.is_relative_to(self.root / "frontend")
                or raw_frontend.get("binary_sha256") != NODE_SHA
                or raw_frontend.get("signature_status") != "Valid"
            ):
                raise LocalRecoveryRefusal("frontend_registry_unverified")
            allowed.append(child)
            launcher_id = _int(registered.get("launcher_pid"))
            launcher_raw = by_pid.get(launcher_id)
            if launcher_raw is not None:
                launcher = ProcessLifetime.from_observation(launcher_raw)
                launcher_arguments = command_tokens(launcher.command)
                if (
                    child.parent_pid != launcher.pid
                    or launcher.created_at != FRONTEND_LAUNCHER_AT
                    or launcher.name != "node.exe"
                    or launcher.executable != child.executable
                    or len(launcher_arguments) != 7
                    or _path(launcher_arguments[0]) != child.executable
                    or _path(launcher_arguments[1]).removeprefix("./")
                    != "node_modules/next/dist/bin/next"
                    or launcher_arguments[2:]
                    != ("dev", "--hostname", "127.0.0.1", "--port", "5173")
                    or launcher_raw.get("binary_sha256") != NODE_SHA
                    or launcher_raw.get("signature_status") != "Valid"
                ):
                    raise LocalRecoveryRefusal("frontend_launcher_unverified")
                allowed.append(launcher)
        return tuple(allowed)

    async def clients_absent(self) -> tuple[str, datetime]:
        self._local()
        try:
            wsl_state = _obj(await self._json(FixedCommand.WSL_STATE))
            host = _obj(await self._json(FixedCommand.HOST))
            host["wsl_state"] = wsl_state
            helper = next(
                (
                    _obj(p)
                    for p in _list(host.get("processes"))
                    if _obj(p).get("pid") == host.get("helper_pid")
                ),
                None,
            )
            helper_lifetime = ProcessLifetime.from_observation(helper)
            expected_helper = command_argv(FixedCommand.HOST)
            if (
                helper_lifetime.executable != _path(POWERSHELL_EXE)
                or helper_lifetime.parent_pid != os.getpid()
                or expected_helper[-1] not in helper_lifetime.command
            ):
                raise LocalRecoveryRefusal("inventory_helper_unverified")
            if self._allowed is None:
                self._allowed = self._initial_allowed(host)
            host["distros"] = [
                line.strip().lstrip("\ufeff")
                for line in (await self.executor.run(FixedCommand.WSL)).splitlines()
                if line.strip()
            ]
            host["portproxy"] = await self.executor.run(FixedCommand.PORTPROXY)
            infrastructure = classify_infrastructure(
                [_obj(p) for p in _list(host.get("processes"))],
                wsl_state,
            )
            if self._infrastructure_sha256 is None:
                self._infrastructure_sha256 = infrastructure.sha256
            elif self._infrastructure_sha256 != infrastructure.sha256:
                raise LocalRecoveryRefusal("infrastructure_lifetime_changed")
            digest = validate_host(host, (*self._allowed, helper_lifetime))
            return digest, datetime.now(UTC)
        except LocalRecoveryRefusal:
            raise
        except Exception:
            raise LocalRecoveryRefusal("local_enumeration_incomplete") from None

    async def stop(self, identity: ServerIdentity) -> ServerIdentity:
        if await self.identity() != identity:
            raise LocalRecoveryRefusal("server_identity_changed")
        await self.executor.run(FixedCommand.STOP)
        container, mount, config = await self._container()
        state = _obj(container.get("State"))
        if (
            state.get("Running") is not False
            or state.get("Pid") != 0
            or mount != identity.mount_sha256
            or config != identity.config_sha256
        ):
            raise LocalRecoveryRefusal("server_stop_unverified")
        return replace(identity, running=False, finished_at=_at(state.get("FinishedAt")))

    async def start(self, identity: ServerIdentity) -> ServerIdentity:
        container, mount, config = await self._container()
        if (
            container.get("Id") != identity.container_id
            or mount != identity.mount_sha256
            or config != identity.config_sha256
            or _obj(container.get("State")).get("Running") is not False
        ):
            raise LocalRecoveryRefusal("server_identity_changed")
        await self.executor.run(FixedCommand.START)
        # Bounded readiness; no second start/recreate/fallback/cleanup.
        for attempt in range(20):
            try:
                return await self.identity()
            except LocalRecoveryRefusal as exc:
                if exc.diagnostic not in {
                    "server_observation_failed",
                    "single_node_topology_unverified",
                }:
                    raise
                if attempt == 19:
                    raise LocalRecoveryRefusal("server_start_unverified") from None
                await asyncio.sleep(0.5)
        raise LocalRecoveryRefusal("server_start_unverified")
