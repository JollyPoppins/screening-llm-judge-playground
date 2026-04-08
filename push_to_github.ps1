# Run from project root with your repo URL, e.g.:
# .\push_to_github.ps1 https://github.com/YOUR_USERNAME/screening-llm-judge.git
param(
    [Parameter(Mandatory=$true)]
    [string]$RepoUrl
)
Set-Location $PSScriptRoot
git remote remove origin 2>$null
git remote add origin $RepoUrl
git push -u origin main
