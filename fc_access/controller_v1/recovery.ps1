param([ValidateSet('observe','reload','click','select-account')][string]$Action='observe',
      [long]$WindowHandle=0,[string]$Name='',[string]$Account='')
# Ordinary official-page recovery for the owned FC Web App document. Authorized
# in AGENTS.md: refresh, normal Login/continue clicks and saved Edge sign-in.
# Never reads, types or exports passwords, cookies, tokens or field values.
# Leaves CAPTCHA, 2FA and security challenges to the user (reported, not acted on).
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
if(!('FCRecoveryInput' -as [type])){Add-Type @'
using System;using System.Runtime.InteropServices;
public class FCRecoveryInput {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr e);
}
'@}
. (Join-Path $PSScriptRoot '..\production_v1\desktop_window.ps1')
$scope=[System.Windows.Automation.TreeScope]::Descendants
$all=[System.Windows.Automation.Condition]::TrueCondition
$TypeProp=[System.Windows.Automation.AutomationElement]::ControlTypeProperty
$WebApp='https://www.ea.com/ea-sports-fc/ultimate-team/web-app/'
$Allowed=@('Login','Log In','NEXT','SIGN IN','Continue',"Let's Play",'Start')

function Out-Json($value){$value|ConvertTo-Json -Compress -Depth 4}
$edge=@([System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$all)|Where-Object {$_.Current.Name -like '*Microsoft*Edge'})
$w=Select-FCEdgeWindow -Candidates $edge -WindowHandle $WindowHandle -HasWebAppTab {
 param($candidate)
 $tabs=@($candidate.FindAll($scope,(New-Object System.Windows.Automation.PropertyCondition($TypeProp,[System.Windows.Automation.ControlType]::TabItem)))|Where-Object {$_.Current.Name -like 'FC Ultimate Team Web App*' -or $_.Current.Name -like '*EA*Sign*'})
 return $tabs.Count -eq 1
}
$h=[long]$w.Current.NativeWindowHandle
function Find-Name($name){$w.FindFirst($scope,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$name)))}
function Get-Url{(Find-Name 'Address and search bar').GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value}
function Get-Kind($url){
 if($url -match '^(https://)?(www\.)?ea\.com/(?:[a-z]{2}-[a-z]{2}/)?ea-sports-fc/ultimate-team/web-app/?$'){return 'official_webapp'}
 if($url -match '^(https://)?(signin|accounts)\.ea\.com/'){return 'official_EA_signin'}
 return 'other'
}
function Read-Page{
 $actions=@();$elements=@();$challenge=$false;$ready=$false;$email=$false
 foreach($e in $w.FindAll($scope,$all)){
  $c=$e.Current
  if($c.IsOffscreen){continue}
  $type=$c.ControlType.ProgrammaticName
  if($type -eq 'ControlType.Text' -and $c.Name -match '(?i)(verification code|security code|captcha|verify (your|it.s) (identity|you)|two.factor|login verification)'){$challenge=$true}
  if($type -eq 'ControlType.Edit' -and $c.AutomationId -eq 'email'){$email=$true}
  # Loaded web app navigation; its name is not an account or session value.
  if($type -eq 'ControlType.Button' -and $c.Name -match '\sTransfers$'){$ready=$true}
  if($type -notin 'ControlType.Button','ControlType.Hyperlink'){continue}
  $normalized=($c.Name -replace "[^a-zA-Z '\s]",'' -replace '\s+',' ').Trim()
  foreach($a in $Allowed){if($normalized -ieq $a){$actions+=$a;$elements+=@{action=$a;element=$e}}}
 }
 return @{actions=@($actions|Select-Object -Unique);elements=$elements;challenge=$challenge;ready=$ready;email=$email}
}
function Click-Element($e){
 if(!(Test-FCEdgeForegroundOwner -WindowHandle $h)){throw 'foreground_changed'}
 # A physical click is an ordinary user gesture, which Edge requires before it
 # releases saved sign-in autofill to the page. Coordinates only, no values.
 # The element can vanish between the read and the click while the page moves on
 # (live 2026-11-22: the second Login during sign-in). Nothing is clicked then.
 try{$p=$e.GetClickablePoint()}catch{throw 'normal_action_ambiguous_or_missing'}
 [void][FCRecoveryInput]::SetCursorPos([int]$p.X,[int]$p.Y)
 [FCRecoveryInput]::mouse_event(2,0,0,0,[UIntPtr]::Zero);[FCRecoveryInput]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}

if($Action -ne 'observe'){Confirm-FCEdgeForeground -WindowHandle $h}
$kind=Get-Kind (Get-Url)
if($Action -eq 'reload'){
 $tabs=@($w.FindAll($scope,(New-Object System.Windows.Automation.PropertyCondition($TypeProp,[System.Windows.Automation.ControlType]::TabItem)))|Where-Object {$_.Current.Name -like 'FC Ultimate Team Web App*' -or $_.Current.Name -like '*EA*Sign*'})
 if($tabs.Count -ne 1){throw 'intended_tab_ambiguous'}
 $p=$null
 if($tabs[0].TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$p)){$p.Select()}else{Click-Element $tabs[0]}
 Start-Sleep -Milliseconds 300
 if(!(Test-FCEdgeForegroundOwner -WindowHandle $h)){throw 'foreground_changed'}
 $bar=Find-Name 'Address and search bar';$bar.SetFocus()
 $bar.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($WebApp)
 [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
 Out-Json @{window=$h;action='reload'}
 return
}
$page=Read-Page
if($Action -eq 'observe'){
 Out-Json @{window=$h;kind=$kind;challenge=$page.challenge;ready=$page.ready;email_field=$page.email;actions=$page.actions;foreground=(Test-FCEdgeForegroundOwner -WindowHandle $h)}
 return
}
if($kind -eq 'other'){throw 'official_EA_page_required'}
if($page.challenge){throw 'user_security_challenge_required'}
if($Action -eq 'click'){
 if($Name -notin $Allowed){throw 'action_not_allowlisted'}
 $found=@($page.elements|Where-Object {$_.action -eq $Name})
 if($found.Count -ne 1){throw 'normal_action_ambiguous_or_missing'}
 Click-Element $found[0].element
 Out-Json @{window=$h;action='click';name=$Name}
 return
}
if($Action -eq 'select-account'){
 if($kind -ne 'official_EA_signin'){throw 'official_EA_signin_required'}
 if($Account -notmatch '^[A-Za-z0-9_.-]{1,64}$'){throw 'account_label_invalid'}
 $field=$w.FindFirst($scope,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'email')))
 if(!$field -or $field.Current.IsOffscreen){throw 'email_control_unavailable'}
 Click-Element $field
 # Type only the operator-designated public account label to filter Edge's
 # saved sign-in suggestions; the saved entry itself supplies the sign-in.
 [System.Windows.Forms.SendKeys]::SendWait('^a');[System.Windows.Forms.SendKeys]::SendWait($Account)
 Start-Sleep -Milliseconds 600
 $suggestions=@($w.FindAll($scope,$all)|Where-Object {!$_.Current.IsOffscreen -and $_.Current.ControlType.ProgrammaticName -in 'ControlType.ListItem','ControlType.MenuItem' -and $_.Current.Name -like "*$Account*"})
 if($suggestions.Count -ne 1){throw 'unique_saved_account_suggestion_required'}
 Click-Element $suggestions[0]
 Out-Json @{window=$h;action='select-account';selected=$true}
 return
}
