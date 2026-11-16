param([ValidateSet('inspect','login','next','sign-in','focus-account','filter-account','submit-account','submit-password','saved-account')][string]$Action='inspect')
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System; using System.Runtime.InteropServices;
public class FCControllerUI {
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
'@
$scope=[System.Windows.Automation.TreeScope]::Descendants
$all=[System.Windows.Automation.Condition]::TrueCondition
$windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$all)
$candidates=@()
foreach($w in $windows){
 if($w.Current.Name -notlike '*Microsoft*Edge*'){continue}
 $bar=$w.FindFirst($scope,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Address and search bar')))
 if(!$bar){continue}
 $address=$bar.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
 # The address is used locally for allowlisting only; never output or persist its query.
 $login=$address -match '^(https://)?(accounts|signin)\.ea\.com/'
 $app=$address -match '^(https://)?(www\.)?ea\.com/ea-sports-fc/ultimate-team/web-app/?$'
 if($login -or $app){$candidates+=@{window=$w;login=$login;app=$app}}
}
if($candidates.Count -eq 0){throw 'verified_EA_window_required'}
$selected=@($candidates|Where-Object {$_.login})
if($selected.Count -eq 0){$selected=$candidates}
if($selected.Count -ne 1){throw 'EA_window_ambiguous'}
$w=$selected[0].window;$h=[IntPtr]$w.Current.NativeWindowHandle
[void][FCControllerUI]::ShowWindow($h,9);[void][FCControllerUI]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 150
if([FCControllerUI]::GetForegroundWindow() -ne $h){throw 'Edge_foreground_control_failed'}
$elements=@($w.FindAll($scope,$all))
$names=@{login='Login';next='NEXT';'sign-in'='SIGN IN';'focus-account'='Email or EA ID'}
if($Action -in @('next','sign-in','focus-account','filter-account','submit-account','submit-password','saved-account') -and !$selected[0].login){throw 'official_EA_login_required'}
if($Action -ne 'inspect'){
 if($Action -eq 'saved-account'){
  # Select the designated normal Edge autofill suggestion. Never read an edit value.
  $buttons=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.ControlType.ProgrammaticName -in @('ControlType.ListItem','ControlType.Button') -and $_.Current.Name -like '*zzorniss*'})
 }elseif($Action -eq 'submit-password'){
  $buttons=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit' -and $_.Current.IsPassword})
 }elseif($Action -in @('focus-account','filter-account','submit-account')){
  $buttons=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit' -and !$_.Current.IsPassword -and $_.Current.Name -ne 'Address and search bar'})
  $named=@($buttons|Where-Object {$_.Current.AutomationId -match '(?i)email|username'})
  if($named.Count -eq 1){$buttons=$named}
  elseif($buttons.Count -eq 2){$buttons=@($buttons|Sort-Object {$_.Current.BoundingRectangle.Top}|Select-Object -First 1)}
 }else{$buttons=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.Name -eq $names[$Action]})}
 if($buttons.Count -ne 1){throw 'exact_login_control_required'}
 if([FCControllerUI]::GetForegroundWindow() -ne $h){throw 'foreground_changed'}
 $pt=$buttons[0].GetClickablePoint();[void][FCControllerUI]::SetCursorPos([int]$pt.X,[int]$pt.Y)
 [FCControllerUI]::mouse_event(2,0,0,0,[UIntPtr]::Zero);[FCControllerUI]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
 if($Action -eq 'focus-account'){[System.Windows.Forms.SendKeys]::SendWait('{DOWN}')}
 if($Action -eq 'filter-account'){[System.Windows.Forms.SendKeys]::SendWait('^a');[System.Windows.Forms.SendKeys]::SendWait('zzorniss')}
 if($Action -in @('submit-account','submit-password')){[System.Windows.Forms.SendKeys]::SendWait('{ESC}');[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')}
}
$out=@{at=[DateTime]::UtcNow.ToString('o');official_login=$selected[0].login;official_app=$selected[0].app;foreground_verified=$true;action=$Action}
foreach($pair in $names.GetEnumerator()){$out[$pair.Key+'_control']=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.Name -eq $pair.Value}).Count -gt 0}
$out.saved_designated_suggestion=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.ControlType.ProgrammaticName -in @('ControlType.ListItem','ControlType.Button') -and $_.Current.Name -like '*zzorniss*'}).Count -gt 0
$out.challenge_visible=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.Name -match '(?i)^(Verify your identity|Security verification|Enter your verification code|CAPTCHA)$'}).Count -gt 0
$out.edit_controls=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit'}).Count
$out.edit_kinds=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit'}|ForEach-Object {@{password=$_.Current.IsPassword;account_id=($_.Current.AutomationId -match '(?i)email|username');address_bar=($_.Current.Name -eq 'Address and search bar')}})
$out.safe_labels=@($elements|Where-Object {!$_.Current.IsOffscreen -and $_.Current.Name -match '(?i)^(Email|Email address|EA ID|Password|Remember me|Forgot your password\?|NEXT|SIGN IN|Sign in|Continue|Continue with Google|Continue with Steam|ACCEPT ALL|Accept all|Reject all|Accept|Close|Email or EA ID|Log in to your EA Account|Sign in to your EA Account)$'}|ForEach-Object {$_.Current.Name}|Select-Object -Unique)
$out|ConvertTo-Json -Compress
