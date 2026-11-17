function Select-FCEdgeWindow {
 param([array]$Candidates,[long]$WindowHandle=0,[scriptblock]$HasWebAppTab)
 $selected=@($Candidates)
 if($WindowHandle -ne 0){$selected=@($selected|Where-Object {$_.Current.NativeWindowHandle -eq $WindowHandle})}
 elseif($selected.Count -gt 1){$selected=@($selected|Where-Object {& $HasWebAppTab $_})}
 if($selected.Count -ne 1){throw 'exactly_one_Edge_window_required'}
 return $selected[0]
}

function Confirm-FCEdgeForeground {
 param([long]$WindowHandle,[hashtable]$Native=$null,[scriptblock]$Pause={Start-Sleep -Milliseconds 100})
 if($WindowHandle -le 0){throw 'verified_window_handle_required'}
 if(!$Native){
  if(!('FCForegroundNative' -as [type])){Add-Type @'
using System;using System.Runtime.InteropServices;
public class FCForegroundNative {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int cmd);
 [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h,uint flag);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
 [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a,uint b,bool attach);
}

'@}
  $Native=@{
   Get={ [FCForegroundNative]::GetForegroundWindow().ToInt64() }
   Restore={param($handle) [FCForegroundNative]::ShowWindow([IntPtr]$handle,9)}
   Set={param($handle) [FCForegroundNative]::SetForegroundWindow([IntPtr]$handle)}
   Bring={param($handle) [FCForegroundNative]::BringWindowToTop([IntPtr]$handle)}
   CurrentThread={ [FCForegroundNative]::GetCurrentThreadId() }
   ForegroundThread={param($handle) [uint32]$fcOwnerProcess=0; [FCForegroundNative]::GetWindowThreadProcessId([IntPtr]$handle,[ref]$fcOwnerProcess)}
   Attach={param($source,$target,$attach) [FCForegroundNative]::AttachThreadInput($source,$target,$attach)}
  }
 }
 [void](& $Native.Restore $WindowHandle);[void](& $Native.Set $WindowHandle);& $Pause
 if((& $Native.Get) -eq $WindowHandle){return}
 $fcSourceThread=& $Native.CurrentThread
 $fcForeground=& $Native.Get
 $fcTargetThread=& $Native.ForegroundThread $fcForeground
 $fcAttached=$false
 try {
  if($fcTargetThread -gt 0 -and $fcSourceThread -ne $fcTargetThread){
   $fcAttached=[bool](& $Native.Attach $fcSourceThread $fcTargetThread $true)
   if(!$fcAttached){throw 'Edge_foreground_control_failed'}
  }
  [void](& $Native.Restore $WindowHandle);[void](& $Native.Bring $WindowHandle)
  [void](& $Native.Set $WindowHandle);& $Pause
  if((& $Native.Get) -ne $WindowHandle){throw 'Edge_foreground_control_failed'}
 } finally {
  if($fcAttached -and !(& $Native.Attach $fcSourceThread $fcTargetThread $false)){throw 'Edge_input_detach_failed'}
 }
}

function Test-FCEdgeForegroundOwner {
 param([long]$WindowHandle,[hashtable]$Native=$null)
 if($WindowHandle -le 0){return $false}
 if(!$Native){
  if(!('FCForegroundNative' -as [type])){return $false}
  $Native=@{Get={[FCForegroundNative]::GetForegroundWindow().ToInt64()};RootOwner={param($handle) [FCForegroundNative]::GetAncestor([IntPtr]$handle,3).ToInt64()}}
 }
 $fcForeground=& $Native.Get
 return $fcForeground -ne 0 -and ($fcForeground -eq $WindowHandle -or (& $Native.RootOwner $fcForeground) -eq $WindowHandle)
}
