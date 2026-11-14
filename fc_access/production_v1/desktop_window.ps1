function Select-FCEdgeWindow {
 param([array]$Candidates,[long]$WindowHandle=0,[scriptblock]$HasWebAppTab)
 $selected=@($Candidates)
 if($WindowHandle -ne 0){$selected=@($selected|Where-Object {$_.Current.NativeWindowHandle -eq $WindowHandle})}
 elseif($selected.Count -gt 1){$selected=@($selected|Where-Object {& $HasWebAppTab $_})}
 if($selected.Count -ne 1){throw 'exactly_one_Edge_window_required'}
 return $selected[0]
}
