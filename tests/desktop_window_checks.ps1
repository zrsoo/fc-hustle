$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../fc_access/production_v1/desktop_window.ps1')
function Candidate($handle,$tabs){return [pscustomobject]@{Current=[pscustomobject]@{NativeWindowHandle=$handle};WebAppTabs=$tabs}}
$a=Candidate 11 0;$b=Candidate 22 1;$c=Candidate 33 0
$has={param($window) $window.WebAppTabs -eq 1}
if((Select-FCEdgeWindow -Candidates @($a,$b,$c) -HasWebAppTab $has).Current.NativeWindowHandle -ne 22){throw 'wrong_window'}
if((Select-FCEdgeWindow -Candidates @($a,$b,$c) -WindowHandle 33 -HasWebAppTab $has).Current.NativeWindowHandle -ne 33){throw 'explicit_window_ignored'}
if((Select-FCEdgeWindow -Candidates @($a) -HasWebAppTab $has).Current.NativeWindowHandle -ne 11){throw 'single_window_regressed'}
foreach($case in @(@(),@($a,$c),@($b,(Candidate 44 1)))){
 $rejected=$false
 try{[void](Select-FCEdgeWindow -Candidates $case -HasWebAppTab $has)}catch{if($_.Exception.Message -eq 'exactly_one_Edge_window_required'){$rejected=$true}else{throw}}
 if(!$rejected){throw 'ambiguous_or_missing_window_accepted'}
}
$rejected=$false
try{[void](Select-FCEdgeWindow -Candidates @($a,$b) -WindowHandle 99 -HasWebAppTab $has)}catch{$rejected=$true}
if(!$rejected){throw 'missing_explicit_window_accepted'}
'PASS desktop window selection: unique intended tab, explicit verified handle, missing and ambiguous fail closed'
