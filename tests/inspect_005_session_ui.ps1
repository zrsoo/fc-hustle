param()
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System; using System.Runtime.InteropServices;
public class FCSessionReadOnlyUI {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@
$scope=[System.Windows.Automation.TreeScope]::Descendants
$w=[System.Windows.Automation.AutomationElement]::FromHandle([FCSessionReadOnlyUI]::GetForegroundWindow())
if($w.Current.Name -notlike '*Microsoft*Edge*'){throw 'foreground_Edge_required'}
$condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,'Address and search bar')
$bar=$w.FindFirst($scope,$condition)
if(!$bar){throw 'official_address_required'}
# Address used only for an exact public-origin check; never emitted or retained.
$address=$bar.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
if($address -notmatch '^(https://)?(www\.)?ea\.com/ea-sports-fc/ultimate-team/web-app/?$'){throw 'official_app_required'}
$texts=@($w.FindAll($scope,[System.Windows.Automation.Condition]::TrueCondition)|Where-Object {
 !$_.Current.IsOffscreen -and $_.Current.ControlType.ProgrammaticName -eq 'ControlType.Text'
}|ForEach-Object {$_.Current.Name})
# Categorize visible public UI messages without printing arbitrary text or edits.
$patterns=@{
 concurrent_login='(?i)(signed|logged).*in.*(elsewhere|another)|(another|other).*(device|session)|console.*(login|log.in)'
 expired_session='(?i)session.*expir|(signed|logged).*out|log.*in.again|sign.*in.again'
 connection_error='(?i)(connect|server).*(lost|error|unavailable|unable)|unable.*connect'
 challenge='(?i)captcha|verify.your.identity|security.verification|verification.code'
 market_error='(?i)(transfer|market).*(error|unavailable|locked)|error.*(transfer|market)'
}
$out=@{observed_at=[DateTime]::UtcNow.ToString('o');foreground_verified=$true;official_app=$true;account_writes=0;visible_text_count=$texts.Count}
foreach($key in $patterns.Keys){$out[$key]=@($texts|Where-Object {$_ -match $patterns[$key]}).Count -gt 0}
$out|ConvertTo-Json -Compress
