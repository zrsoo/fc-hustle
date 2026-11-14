param([string]$Action='inspect',[string]$Name='',[string]$Url='', [switch]$JsonOnly,[long]$WindowHandle=0)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System; using System.Runtime.InteropServices;
public class FCDesktop {
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
$edge=@($windows | Where-Object {$_.Current.Name -like '*Microsoft*Edge'})
. (Join-Path $PSScriptRoot 'desktop_window.ps1')
$w=Select-FCEdgeWindow -Candidates $edge -WindowHandle $WindowHandle -HasWebAppTab {
 param($candidate)
 $tabs=@($candidate.FindAll($scope,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::TabItem)))|Where-Object {$_.Current.Name -like 'FC Ultimate Team Web App*'})
 return $tabs.Count -eq 1
}
$h=[IntPtr]$w.Current.NativeWindowHandle
if($Action -eq 'load-path') {
 $modal=$w.FindFirst($scope,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Window)))
 if($modal){$h=[IntPtr]$modal.Current.NativeWindowHandle}
}
[void][FCDesktop]::ShowWindow($h,9)
[void][FCDesktop]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 250
if([FCDesktop]::GetForegroundWindow() -ne $h){throw 'Edge_foreground_control_failed'}
function Find-Name($name) {
 $cond=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$name)
 return $w.FindFirst($scope,$cond)
}
function Activate($e){
 if(!$e){throw 'UI_element_missing'}
 $fg=[System.Windows.Automation.AutomationElement]::FromHandle([FCDesktop]::GetForegroundWindow())
 if(($Action -eq 'load-path' -and [FCDesktop]::GetForegroundWindow() -ne $h) -or ($Action -ne 'load-path' -and $fg.Current.ProcessId -ne $w.Current.ProcessId)){throw 'foreground_changed'}
 $p=$null
 if($e.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$p)){$p.Invoke();return}
 if($e.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$p)){$p.Select();return}
 $pt=$e.GetClickablePoint(); [void][FCDesktop]::SetCursorPos([int]$pt.X,[int]$pt.Y)
 [FCDesktop]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [FCDesktop]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
if($Action -eq 'navigate'){
 if($Url -notin @('edge://extensions/','https://www.ea.com/ea-sports-fc/ultimate-team/web-app/')){throw 'URL_not_allowlisted'}
 $bar=Find-Name 'Address and search bar'
 $p=$bar.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
 $bar.SetFocus();$p.SetValue($Url);[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
} elseif($Action -eq 'attach') {
 $currentUrl=(Find-Name 'Address and search bar').GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
 if($currentUrl -notmatch '^(https://)?(www\.)?ea\.com/(?:[a-z]{2}-[a-z]{2}/)?ea-sports-fc/ultimate-team/web-app/?$'){throw 'official_tab_required'}
 Activate (Find-Name 'Extensions');Start-Sleep -Milliseconds 300
 $btn=@($w.FindAll($scope,$all)|Where-Object {$_.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $_.Current.Name -like 'FC27 production one-shot bridge Allowed only when clicked*'})
 if($btn.Count -ne 1){throw 'extension_button_ambiguous'}
 Activate $btn[0]
} elseif($Action -eq 'click') { Activate (Find-Name $Name)
} elseif($Action -eq 'select-ea') {
 $tabs=$w.FindAll($scope,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::TabItem)))
 $tab=@($tabs|Where-Object {$_.Current.Name -like 'FC Ultimate Team Web App*'})
 if($tab.Count -ne 1){throw 'intended_tab_ambiguous'};Activate $tab[0]
} elseif($Action -eq 'select-manager') {
 $tab=$w.FindAll($scope,$all)|Where-Object {$_.Current.ControlType.ProgrammaticName -eq 'ControlType.TabItem' -and $_.Current.Name -like 'Extensions*'}|Select-Object -First 1
 Activate $tab
} elseif($Action -eq 'reload-extension') {
 $card=$w.FindAll($scope,$all)|Where-Object {$_.Current.ControlType.ProgrammaticName -eq 'ControlType.ListItem' -and $_.Current.Name -like 'FC27 production one-shot bridge*'}|Select-Object -First 1
 if(!$card){throw 'reviewed_extension_card_missing'}
 $reload=$card.FindFirst($scope,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Reload')))
 Activate $reload
} elseif($Action -eq 'transfers') {
 $btn=$w.FindAll($scope,$all)|Where-Object {$_.Current.ControlType.ProgrammaticName -eq 'ControlType.Button' -and $_.Current.Name -match '\sTransfers$'}|Select-Object -First 1
 Activate $btn
} elseif($Action -eq 'targets-text') {
 foreach($e in $w.FindAll($scope,$all)){
  $n=$e.Current.Name
  if(!$e.Current.IsOffscreen -and $e.Current.ControlType.ProgrammaticName -eq 'ControlType.Text' -and $n.Length -le 150 -and $n -match '(?i)^(transfer targets|transfer list|transfer market|winning|outbid|expired|active|available items|items|watching|watched items|won items|expired items|items you.*|no.*targets|you.*targets|\d+\s*/\s*\d+|\d+)$'){'TARGET_TEXT | '+$n}
 }
} elseif($Action -eq 'load-path') {
 $dialog=$w.FindFirst($scope,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Window)))
 if(!$dialog){throw 'folder_dialog_missing'}
 if($Name -ne 'C:\hustle\fc-hustle\browser\production-v1'){throw 'path_not_allowlisted'}
 [System.Windows.Forms.SendKeys]::SendWait('%d');Start-Sleep -Milliseconds 100
 [System.Windows.Forms.SendKeys]::SendWait($Name);[System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
 Start-Sleep -Milliseconds 500
 Activate (Find-Name 'Select Folder')
} elseif($Action -notin @('inspect','preflight-json')) {throw 'unknown_action'}
Start-Sleep -Milliseconds 350
$bar=Find-Name 'Address and search bar'
$value=$bar.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
$official=$value -match '^(https://)?(www\.)?ea\.com/(?:[a-z]{2}-[a-z]{2}/)?ea-sports-fc/ultimate-team/web-app/?$'
@{observed_at=[DateTime]::UtcNow.ToString('o');edge_control_verified=$true;foreground_verified=([FCDesktop]::GetForegroundWindow() -eq $h);official_tab=$official;extensions_manager=($value -like 'edge://extensions*')}|ConvertTo-Json -Compress
if($JsonOnly -or $Action -eq 'preflight-json'){return}
foreach($e in $w.FindAll($scope,$all)) {
 $type=$e.Current.ControlType.ProgrammaticName
 if($type -in 'ControlType.Button','ControlType.TabItem','ControlType.CheckBox'){
  '{0} | {1}' -f $type,$e.Current.Name
 }
}

