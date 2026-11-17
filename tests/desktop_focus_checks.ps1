$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../fc_access/production_v1/desktop_window.ps1')
foreach($mode in @('normal','fallback','denied','attach-denied','set-error')){
 $state=@{foreground=7;sets=0;joins=0;detaches=0}
 $native=@{
  Get={$state.foreground};Restore={param($h) $true};Bring={param($h) $true}
  CurrentThread={11};ForegroundThread={param($h) 22}
  Set={param($h)
   $state.sets++
   if($mode -eq 'set-error' -and $state.sets -gt 1){throw 'fixture_set_error'}
   if($mode -eq 'normal' -or ($mode -eq 'fallback' -and $state.joins -gt 0)){$state.foreground=$h}
   $true
  }
  Attach={param($a,$b,$join)
   if($a -ne 11 -or $b -ne 22){throw 'wrong_input_threads'}
   if($join){$state.joins++;return $mode -ne 'attach-denied'}
   $state.detaches++;return $true
  }
 }
 $failed=$false
 try{Confirm-FCEdgeForeground -WindowHandle 99 -Native $native -Pause {}}catch{$failed=$true}
 if($failed -ne ($mode -in @('denied','attach-denied','set-error'))){throw 'wrong_focus_verdict'}
 if($mode -eq 'normal' -and $state.joins -ne 0){throw 'unnecessary_attach'}
 if($mode -in @('fallback','denied','set-error') -and $state.detaches -ne 1){throw 'input_not_detached'}
 if($mode -eq 'attach-denied' -and $state.detaches -ne 0){throw 'unowned_detach'}
}
foreach($case in @(@{foreground=99;root=99;expected=$true},@{foreground=77;root=99;expected=$true},@{foreground=77;root=88;expected=$false},@{foreground=0;root=99;expected=$false})){
 $native=@{Get={$case.foreground};RootOwner={param($h) $case.root}}
 if((Test-FCEdgeForegroundOwner -WindowHandle 99 -Native $native) -ne $case.expected){throw 'wrong_popup_ownership_verdict'}
}
'PASS 9 bounded foreground/owned-popup policy cases; no real desktop input'
