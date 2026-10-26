
(function () {
"use strict";
var tg=window.Telegram&&window.Telegram.WebApp;
try{if(tg){tg.ready();tg.expand();tg.setHeaderColor("#030605");tg.setBackgroundColor("#030605");}}catch(e){}
var DEMO=!(tg&&tg.initData),FARM_MS=8*60*60*1000,DAILY_MS=24*60*60*1000;
var tasks=[{id:"welcome",name:"Explore ZENQORY",desc:"Discover your new digital rewards space",reward:30,icon:"i-spark"},{id:"safety",name:"Learn about reward points",desc:"Understand our pre-launch points system",reward:20,icon:"i-shield"},{id:"profile",name:"View your profile",desc:"Discover your Explorer identity",reward:15,icon:"i-user"}];
var $=function(id){return document.getElementById(id);};
var empty=function(){return{balance:0,farmStart:null,farmCount:0,lastDaily:null,tasks:[],refCount:0,refPoints:0,firstName:"Explorer",id:"Preview",history:[]};};
var state=empty(),referralLink="",tab="home",busy=false,toastTimeout=null,demoFinish=null;
var fmt=function(n){return new Intl.NumberFormat("en-US").format(Math.max(0,Math.floor(Number(n)||0)));};
var logoIcon=function(icon){return '<svg aria-hidden="true"><use href="#'+icon+'"></use></svg>';};
var now=function(){return Date.now();};
function normalize(data){if(!data||typeof data!=="object")return;state=Object.assign({},state,data);if(!Array.isArray(state.tasks))state.tasks=[];if(!Array.isArray(state.history))state.history=[];if(typeof data.referralLink==="string")referralLink=data.referralLink;}
function persist(){if(DEMO){try{localStorage.setItem("zenqory-v3-demo",JSON.stringify(state));}catch(e){}}}
function notice(message){var box=$("toast");box.textContent=message;box.classList.add("visible");clearTimeout(toastTimeout);toastTimeout=setTimeout(function(){box.classList.remove("visible");},3300);}
function modal(title,description){$("modal-title").textContent=title;$("modal-description").textContent=description;$("modal-backdrop").hidden=false;}
function closeModal(){$("modal-backdrop").hidden=true;}
function clock(ms){var sec=Math.max(0,Math.ceil(ms/1000)),h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=sec%60;return[String(h).padStart(2,"0"),String(m).padStart(2,"0"),String(s).padStart(2,"0")].join(":");}
function record(type,amount){state.history.unshift({type:type,amount:amount,at:Date.now()});state.history=state.history.slice(0,15);}
async function callApi(path,method){var response=await fetch("/api"+path,{method:method||"GET",headers:{"X-Telegram-Init-Data":tg&&tg.initData?tg.initData:"","Content-Type":"application/json"}});var body;try{body=await response.json();}catch(e){throw new Error("Service returned an unexpected response");}if(!response.ok){throw new Error(body.detail||"Request failed");}return body;}
async function perform(path,demoAction,success){if(busy)return;busy=true;try{if(DEMO){demoAction();persist();}else{normalize(await callApi(path,"POST"));}render();notice(success);}catch(e){notice(e.message||"Something went wrong");}finally{busy=false;renderFarming();}}
function openTab(name){if(["home","earn","friends","wallet","profile"].indexOf(name)<0)return;tab=name;document.querySelectorAll("[data-screen]").forEach(function(element){element.classList.toggle("active",element.dataset.screen===name);});document.querySelectorAll("[data-tab]").forEach(function(button){var active=button.dataset.tab===name;button.classList.toggle("active",active);if(active)button.setAttribute("aria-current","page");else button.removeAttribute("aria-current");});window.scrollTo({top:0,behavior:"smooth"});try{if(tg&&tg.HapticFeedback)tg.HapticFeedback.selectionChanged();}catch(e){}}
function renderFarming(){var begin=state.farmStart,elapsed=begin===null?0:Math.max(0,now()-begin),progress=begin===null?0:Math.min(100,100*elapsed/FARM_MS),ready=begin!==null&&elapsed>=FARM_MS;
$("farm-timer").textContent=begin===null?"08:00:00":ready?"00:00:00":clock(FARM_MS-elapsed);
$("farm-caption").textContent=begin===null?"AWAITING ACTIVATION":ready?"REWARD READY":"FARMING PROTOCOL ACTIVE";
$("farm-state").textContent=begin===null?"READY TO FARM":ready?"CYCLE COMPLETE":"MINING POINTS";
$("farm-percent").textContent=Math.floor(progress)+"%";
$("protocol-state").textContent=begin===null?"STANDBY":ready?"CLAIM READY":"FARMING";
$("protocol-progress").textContent=Math.floor(progress)+"%";
$("protocol-cycles").textContent=fmt(state.farmCount);
$("farm-progress").style.width=progress+"%";
$("radial-progress").style.background="conic-gradient(#70ff8f "+(progress*3.6)+"deg,#183e26 "+(progress*3.6)+"deg)";
var fb=$("farm-button");fb.disabled=busy||(begin!==null&&!ready);
fb.innerHTML=logoIcon("i-lightning")+"<span>"+(begin===null?"START FARMING":ready?"CLAIM +80 POINTS":"FARMING IN PROGRESS")+"</span>"+logoIcon("i-arrow");
if(DEMO&&begin!==null&&!ready){if(!demoFinish){demoFinish=document.createElement("button");demoFinish.type="button";demoFinish.className="demo-fast";demoFinish.textContent="Preview: finish this cycle";demoFinish.addEventListener("click",function(){state.farmStart=now()-FARM_MS;persist();render();notice("Cycle completed in preview — Claim is ready");});$("farm-button").after(demoFinish);}demoFinish.hidden=false;}else if(demoFinish){demoFinish.hidden=true;}
var dailyReady=!state.lastDaily||now()-state.lastDaily>=DAILY_MS;
$("daily-card").disabled=busy||!dailyReady;$("daily-status").textContent=dailyReady?"READY TO CLAIM":"NEXT IN "+clock(DAILY_MS-(now()-state.lastDaily));$("daily-sub").textContent=dailyReady?"Collect +20 daily points":"Already claimed this cycle";
}
function renderMissions(){var claimed=state.tasks||[],count=tasks.filter(function(t){return claimed.indexOf(t.id)!==-1;}).length,html="";
tasks.forEach(function(t){var done=claimed.indexOf(t.id)!==-1;html+='<article class="mission-item"><span class="mission-icon">'+logoIcon(t.icon)+'</span><div class="mission-info"><strong>'+t.name+'</strong><small>'+t.desc+'</small><em>+'+t.reward+' ZNQY POINTS</em></div><button class="mission-btn" data-claim-task="'+t.id+'" '+(done?'disabled':'')+'>'+(done?"DONE ✓":"CLAIM")+'</button></article>';});
$("mission-list").innerHTML=html;$("mission-done").textContent=count;$("mission-progress").style.width=(count/tasks.length*100)+"%";$("mission-signal").textContent=count+"/"+tasks.length+" COMPLETE";$("earn-done").textContent=count+"/"+tasks.length;$("quick-tasks").textContent=count+" / "+tasks.length+" COMPLETED";$("earn-farm").textContent=fmt(state.farmCount);$("earn-daily").textContent=(!state.lastDaily||now()-state.lastDaily>=DAILY_MS)?"READY":"CLAIMED";}
function renderActivity(){var entries=state.history||[];var box=$("activity-list");if(!entries.length){box.innerHTML='<div class="activity-empty">No transactions yet. Start farming to create your first reward activity. Your points are not on-chain tokens.</div>';return;}box.innerHTML=entries.slice(0,8).map(function(row){var label=String(row.type||"Reward").replace(/[<>]/g,""),amount=fmt(row.amount);return '<div class="activity-item">'+logoIcon("i-gift")+'<span>'+label+'</span><strong>+'+amount+' PTS</strong></div>';}).join("");}
function renderCyber(){
  $("session-status").textContent=DEMO?"PREVIEW • LOCAL ONLY":"TELEGRAM SESSION";
  $("network-spectrum-count").textContent=fmt(state.refCount)+" INVITED FRIEND"+(state.refCount===1?"":"S");
  $("profile-code").textContent=DEMO?"PREVIEW":String(state.id||"").slice(-6);
  var count=Math.max(0,Number(state.farmCount)||0),stage=count%5,percentage=100*stage/5;
  $("rank-goal").textContent=stage+" / 5 CYCLES";
  $("rank-fill").style.width=percentage+"%";
  var badges=[["badge-pioneer","badge-pioneer-label",count>=1],["badge-claim","badge-claim-label",count>=1],["badge-connector","badge-connector-label",Number(state.refCount)>=1]];
  badges.forEach(function(item){var node=$(item[0]);node.classList.toggle("unlocked",item[2]);$(item[1]).textContent=item[2]?"EARNED":"LOCKED";});
  var feed=$("home-activity-feed"),entries=Array.isArray(state.history)?state.history.slice(0,3):[];
  if(!entries.length){feed.innerHTML='<div class="signal-entry signal-empty">'+logoIcon("i-spark")+'<span>Your reward activity will appear here after your first claim.</span></div>';}
  else{feed.replaceChildren();entries.forEach(function(row){var el=document.createElement("div");el.className="signal-entry";var ico=document.createElement("span");ico.className="signal-entry-icon";ico.innerHTML=logoIcon("i-spark");var label=document.createElement("span");label.className="signal-entry-label";label.textContent=String(row.type||"Reward");var amount=document.createElement("strong");amount.textContent="+"+fmt(row.amount)+" PTS";el.append(ico,label,amount);feed.appendChild(el);});}
}
function render(){document.querySelectorAll("[data-balance]").forEach(function(node){node.textContent=fmt(state.balance);});var name=String(state.firstName||"Explorer").slice(0,55);$("profile-name").textContent=name;$("profile-initial").textContent=(name[0]||"Z").toUpperCase();$("profile-farms").textContent=fmt(state.farmCount);$("profile-friends").textContent=fmt(state.refCount);$("top-level").textContent=Math.max(1,1+Math.floor((state.farmCount||0)/5));$("profile-member").textContent=DEMO?"PREVIEW MEMBER":"TELEGRAM MEMBER #"+String(state.id).slice(-6);$("friends-total").textContent=fmt(state.refCount);$("friends-points").textContent=fmt(state.refPoints);$("quick-referrals").textContent=fmt(state.refCount)+" FRIENDS JOINED";$("referral-code").textContent=referralLink?referralLink.replace(/^https?:\/\/t\.me\//,""):"Connect Telegram to invite";$("copy-referral").disabled=!referralLink;$("invite-button").disabled=!referralLink;renderFarming();renderMissions();renderActivity();renderCyber();}
async function startOrClaim(){if(state.farmStart===null){await perform("/farm/start",function(){state.farmStart=now();},"Farming activated. Your 8-hour cycle has started.");}else if(now()-state.farmStart>=FARM_MS){await perform("/farm/claim",function(){state.farmStart=null;state.farmCount+=1;state.balance+=80;record("Farming reward",80);},"Success! You claimed 80 ZENQORY points.");}}
function claimDaily(){if(state.lastDaily&&now()-state.lastDaily<DAILY_MS)return;perform("/daily",function(){state.lastDaily=now();state.balance+=20;record("Daily reward",20);},"+20 points added to your rewards balance");}
function claimTask(id){var task=tasks.find(function(t){return t.id===id;});if(!task||state.tasks.indexOf(id)!==-1)return;if(id==="safety"){modal("Rewards are not cryptocurrency","ZENQORY points are pre-launch, off-chain loyalty rewards. They cannot currently be sold, withdrawn or exchanged, and have no guaranteed future value. This learning mission provides an educational points reward.");}
perform("/tasks/"+id,function(){state.tasks.push(id);state.balance+=task.reward;record(task.name,task.reward);},"Mission complete! +"+task.reward+" points");}
function share(){if(!referralLink){modal("Open inside Telegram","Your personal invite link appears after opening ZENQORY through your official Telegram Mini App.");return;}var uri="https://t.me/share/url?url="+encodeURIComponent(referralLink)+"&text="+encodeURIComponent("Join ZENQORY — an early digital rewards community.");try{if(tg&&tg.openTelegramLink)tg.openTelegramLink(uri);else window.open(uri,"_blank","noopener,noreferrer");}catch(e){window.open(uri,"_blank","noopener,noreferrer");}}
async function copyReferral(){if(!referralLink)return;try{await navigator.clipboard.writeText(referralLink);notice("Invite link copied");}catch(e){modal("Your invite link",referralLink);}}
function showInfo(kind){var info={
notification:["Notifications","Farming reminders and major ecosystem updates will appear here as we develop the official Telegram bot."],
settings:["ZENQORY Settings","Account settings, language, safety and help options are available from the Profile tab."],
account:["Telegram Identity","Your account is linked to your Telegram identity when opened as a verified Mini App. No separate password is stored here."],
security:["Security First","Telegram session data is verified on the server. We never need your wallet seed phrase or private keys. Never share them with anyone."],
language:["Language Settings","English is the current app language. Hausa localization is planned for a later version."],
support:["How ZENQORY Works","Start an 8-hour farming cycle. When complete, press Claim to collect points. You can also collect a daily bonus, complete small quests and invite real friends."],
wallet:["TON Wallet — Coming Later","This release tracks off-chain reward points. TON Connect, deposits, withdrawals and token claims are disabled until secure implementation and review."],
withdraw:["Withdrawals Not Available","ZENQORY points currently have no cash value or withdrawal route. A token launch or exchange listing has not been promised."]
};var item=info[kind]||info.support;modal(item[0],item[1]);}
$("farm-button").addEventListener("click",startOrClaim);$("daily-card").addEventListener("click",claimDaily);$("mission-list").addEventListener("click",function(event){var btn=event.target.closest("[data-claim-task]");if(btn)claimTask(btn.getAttribute("data-claim-task"));});
document.querySelectorAll("[data-tab]").forEach(function(button){button.addEventListener("click",function(){openTab(button.dataset.tab);});});document.querySelectorAll("[data-go]").forEach(function(node){node.addEventListener("click",function(){openTab(node.dataset.go);});node.addEventListener("keydown",function(e){if(e.key==="Enter")openTab(node.dataset.go);});});
$("avatar-button").addEventListener("click",function(){openTab("profile");});$("settings-button").addEventListener("click",function(){openTab("profile");});$("notification-button").addEventListener("click",function(){showInfo("notification");});$("copy-referral").addEventListener("click",copyReferral);$("invite-button").addEventListener("click",share);
$("wallet-connect").addEventListener("click",function(){showInfo("wallet");});$("wallet-withdraw").addEventListener("click",function(){showInfo("withdraw");});
["account","notifications","security","language","support"].forEach(function(item){var btn=$(item+"-setting");if(btn)btn.addEventListener("click",function(){showInfo(item==="notifications"?"notification":item);});});
$("modal-close").addEventListener("click",closeModal);$("modal-ok").addEventListener("click",closeModal);$("modal-backdrop").addEventListener("click",function(e){if(e.target===$("modal-backdrop"))closeModal();});document.addEventListener("keydown",function(e){if(e.key==="Escape")closeModal();});
if(DEMO){try{normalize(JSON.parse(localStorage.getItem("zenqory-v3-demo")||"null"));}catch(e){}$("preview-strip").hidden=false;render();}else{$("preview-strip").hidden=true;if(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user){state.firstName=tg.initDataUnsafe.user.first_name||"Explorer";}render();callApi("/me","GET").then(function(payload){normalize(payload);render();}).catch(function(error){notice("Unable to connect securely: "+error.message);$("farm-button").disabled=true;$("daily-card").disabled=true;modal("Connection required","Could not initialize your verified Telegram rewards account. Please reopen the Mini App from the official bot, or contact the team if the problem persists.");});}
setInterval(function(){renderFarming();if(tab==="earn")$("earn-daily").textContent=(!state.lastDaily||now()-state.lastDaily>=DAILY_MS)?"READY":"CLAIMED";},1000);
})();
