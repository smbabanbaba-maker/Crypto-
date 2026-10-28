
(function () {
"use strict";
var tg=window.Telegram&&window.Telegram.WebApp;
try{if(tg){tg.ready();tg.expand();tg.setHeaderColor("#030605");tg.setBackgroundColor("#030605");}}catch(e){}
var hasTelegramSession=!!(tg&&tg.initData),isTelegramClient=!!(tg&&tg.platform&&tg.platform!=="unknown"),DEMO=!hasTelegramSession&&!isTelegramClient,FARM_MS=8*60*60*1000,DAILY_MS=24*60*60*1000;
// Keep original mission IDs for backwards-compatible, once-only rewards.
var tasks=[{id:"welcome",name:"Start your first farming cycle",desc:"Start a real 8-hour cycle to unlock this reward",reward:30,icon:"i-lightning"},{id:"safety",name:"Claim your first farming reward",desc:"Complete an 8-hour cycle and claim your points",reward:20,icon:"i-shield"},{id:"profile",name:"Activate your first invited friend",desc:"Invite a friend who completes their first farm claim",reward:15,icon:"i-friends"}];
var $=function(id){return document.getElementById(id);};
var empty=function(){return{balance:0,farmStart:null,farmCount:0,farmReward:80,nextFarmReward:80,miningBoostPercent:0,maxMiningBoostPercent:20,taskEligibility:{welcome:false,safety:false,profile:false},lastDaily:null,tasks:[],refCount:0,activeRefCount:0,refPoints:0,firstName:"Explorer",photoUrl:null,referralMembers:[],missions:null,isAdmin:false,id:"Preview",history:[]};};
var state=empty(),referralLink="",referralBotLink="",tab="home",busy=false,toastTimeout=null,demoFinish=null;var telegramVerified=false,accountReady=false,connectionIssue="",lastRefreshAt=0,refreshing=false;var APP_URL="https://crypto-jade-nine.vercel.app";
var fmt=function(n){return new Intl.NumberFormat("en-US").format(Math.max(0,Math.floor(Number(n)||0)));};
var logoIcon=function(icon){return '<svg aria-hidden="true"><use href="#'+icon+'"></use></svg>';};
var now=function(){return Date.now();};
function normalize(data){if(!data||typeof data!=="object")return;state=Object.assign({},state,data);if(!Array.isArray(state.tasks))state.tasks=[];if(!Array.isArray(state.history))state.history=[];if(!Array.isArray(state.referralMembers))state.referralMembers=[];if(!Array.isArray(state.missions))state.missions=null;if(typeof data.referralLink==="string")referralLink=data.referralLink;if(typeof data.referralBotLink==="string")referralBotLink=data.referralBotLink;}
function previewKey(){var user=tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user;return user&&user.id?"zenqory-v3-demo-"+String(user.id):"zenqory-v3-demo";}
function loadPreview(){state=empty();var person=tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user;try{normalize(JSON.parse(localStorage.getItem(previewKey())||"null"));}catch(e){}if(person&&person.first_name)state.firstName=String(person.first_name).slice(0,60);if(person)state.photoUrl=safeAvatarURL(person.photo_url);referralLink=APP_URL;referralBotLink="";DEMO=true;render();}
function persist(){if(DEMO){try{localStorage.setItem(previewKey(),JSON.stringify(state));}catch(e){}}}
function notice(message){var box=$("toast");box.textContent=message;box.classList.add("visible");clearTimeout(toastTimeout);toastTimeout=setTimeout(function(){box.classList.remove("visible");},3300);}
function modal(title,description){$("modal-title").textContent=title;$("modal-description").textContent=description;$("modal-backdrop").hidden=false;}
function sessionGuide(title,description){
  // Keep the reason available from Profile > Account, never overlay Home.
  connectionIssue=description||title||"Telegram rewards are not connected.";
}
function hideSessionGuide(){connectionIssue="";}
function connectionSummary(){
  if(accountReady)return "Telegram identity verified. Your reward points are securely stored on the server.";
  if(telegramVerified)return "Your Telegram identity is verified, but your rewards account is temporarily unavailable. Tap Retry Secure Login in Profile.";
  if(connectionIssue)return connectionIssue;
  return DEMO?"Browser preview: points are stored only on this device.":"Checking your secure Telegram session and reward storage.";
}
function closeModal(){$("modal-backdrop").hidden=true;}
function clock(ms){var sec=Math.max(0,Math.ceil(ms/1000)),h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=sec%60;return[String(h).padStart(2,"0"),String(m).padStart(2,"0"),String(s).padStart(2,"0")].join(":");}
function record(type,amount){state.history.unshift({type:type,amount:amount,at:Date.now()});state.history=state.history.slice(0,15);}
async function callApi(path,method,payload){var response=await fetch("/api"+path,{method:method||"GET",headers:{"X-Telegram-Init-Data":tg&&tg.initData?tg.initData:"","Content-Type":"application/json"},body:payload===undefined?undefined:JSON.stringify(payload)});var body;try{body=await response.json();}catch(e){throw new Error("Service returned an unexpected response");}if(!response.ok){var error=new Error(body.detail||"Request failed");error.status=response.status;throw error;}return body;}
async function perform(path,demoAction,success){if(busy)return;if(!DEMO&&!accountReady){openTab("profile");notice("Reconnect Telegram before claiming rewards.");return;}busy=true;try{if(DEMO){demoAction();persist();}else{normalize(await callApi(path,"POST"));}render();notice(success);}catch(e){notice(e.message||"Something went wrong");}finally{busy=false;renderFarming();}}
async function refreshLiveState(){
  if(DEMO||!accountReady||busy||refreshing||now()-lastRefreshAt<30000)return;
  lastRefreshAt=now();refreshing=true;
  try{
    var snapshot=await callApi("/me","GET");
    if(accountReady&&!DEMO){normalize(snapshot);render();}
  }catch(error){
    // A fresh authorization failure must not silently leave a stale live balance.
    if(error&&error.status===401){
      accountReady=false;state=empty();
      sessionGuide("Secure login","Your Telegram session has expired. Reopen the official Mini App, then reconnect.");
      render();
    }
  }finally{refreshing=false;}
}
function openTab(name){if(["home","earn","friends","wallet","profile","admin"].indexOf(name)<0)return;if(name==="admin"&&(!accountReady||!state.isAdmin)){notice("Administrator access is restricted.");return;}tab=name;document.querySelectorAll("[data-screen]").forEach(function(element){element.classList.toggle("active",element.dataset.screen===name);});document.querySelectorAll("[data-tab]").forEach(function(button){var active=button.dataset.tab===name;button.classList.toggle("active",active);if(active)button.setAttribute("aria-current","page");else button.removeAttribute("aria-current");});var page=document.querySelector(".screen.active");if(page){page.scrollTop=0;}try{if(tg&&tg.HapticFeedback)tg.HapticFeedback.selectionChanged();}catch(e){}if(name==="friends"||name==="home"||name==="earn")refreshLiveState();if(name==="admin")loadAdminOverview();}
function renderFarming(){var begin=state.farmStart,elapsed=begin===null?0:Math.max(0,now()-begin),progress=begin===null?0:Math.min(100,100*elapsed/FARM_MS),ready=begin!==null&&elapsed>=FARM_MS;
$("farm-timer").textContent=begin===null?"08:00:00":ready?"00:00:00":clock(FARM_MS-elapsed);
$("farm-caption").textContent=begin===null?"AWAITING ACTIVATION":ready?"REWARD READY":"FARMING PROTOCOL ACTIVE";
$("farm-state").textContent=begin===null?"READY TO FARM":ready?"CYCLE COMPLETE":"MINING POINTS";
$("farm-percent").textContent=Math.floor(progress)+"%";
var farmingCard=document.querySelector(".farm-card");if(farmingCard)farmingCard.dataset.phase=begin===null?"standby":ready?"ready":"active";
$("protocol-state").textContent=begin===null?"STANDBY":ready?"CLAIM READY":"FARMING";
$("protocol-progress").textContent=Math.floor(progress)+"%";
$("protocol-cycles").textContent=fmt(state.farmCount);
$("farm-progress").style.width=progress+"%";
$("radial-progress").style.background="conic-gradient(#70ff8f "+(progress*3.6)+"deg,#183e26 "+(progress*3.6)+"deg)";
var fb=$("farm-button");fb.disabled=busy||(!DEMO&&!accountReady)||(begin!==null&&!ready);
var claimAmount=Math.max(80,Math.min(96,Number(state.farmReward)||80));
fb.innerHTML=logoIcon("i-lightning")+"<span>"+(begin===null?"START FARMING":ready?"CLAIM +"+fmt(claimAmount)+" POINTS":"FARMING IN PROGRESS")+"</span>"+logoIcon("i-arrow");
if(DEMO&&begin!==null&&!ready){if(!demoFinish){demoFinish=document.createElement("button");demoFinish.type="button";demoFinish.className="demo-fast";demoFinish.textContent="Preview: finish this cycle";demoFinish.addEventListener("click",function(){state.farmStart=now()-FARM_MS;persist();render();notice("Cycle completed in preview — Claim is ready");});$("farm-button").after(demoFinish);}demoFinish.hidden=false;}else if(demoFinish){demoFinish.hidden=true;}
var dailyReady=!state.lastDaily||now()-state.lastDaily>=DAILY_MS;
$("daily-card").disabled=busy||(!DEMO&&!accountReady)||!dailyReady;$("daily-status").textContent=dailyReady?"READY TO CLAIM":"NEXT IN "+clock(DAILY_MS-(now()-state.lastDaily));$("daily-sub").textContent=dailyReady?"Collect +20 daily points":"Already claimed this cycle";
}
function missionCatalog(){return !DEMO&&Array.isArray(state.missions)?state.missions:tasks;}
function missionUnlocked(id){
  if(DEMO){
    if(id==="welcome")return state.farmStart!==null||Number(state.farmCount)>0;
    if(id==="safety")return Number(state.farmCount)>0;
    if(id==="profile")return Number(state.activeRefCount)>0;
    return false;
  }
  var mission=missionCatalog().find(function(item){return item.id===id;});
  return !!(mission&&(mission.eligible||mission.verificationRequired));
}
function renderMissions(){
  var claimed=Array.isArray(state.tasks)?state.tasks:[],catalog=missionCatalog();
  var count=catalog.filter(function(t){return claimed.indexOf(t.id)!==-1;}).length;
  var root=$("mission-list");root.replaceChildren();
  catalog.forEach(function(t){
    var done=claimed.indexOf(t.id)!==-1;
    var unlocked=missionUnlocked(t.id),claimable=unlocked&&(DEMO||accountReady)&&!done;
    var verified=!!t.verificationRequired,link=safeMissionLink(t.link||"");
    var item=document.createElement("article");
    item.className="mission-item"+(!done&&!unlocked?" mission-locked":"");
    var icon=document.createElement("span");icon.className="mission-icon";
    var iconName=t.kind==="active_referrals"?"i-friends":t.kind==="telegram_channel"?"i-link":
      t.kind==="farm_cycles"?"i-lightning":t.icon==="i-shield"?"i-shield":"i-lightning";
    icon.innerHTML=logoIcon(iconName);
    var info=document.createElement("div");info.className="mission-info";
    var title=document.createElement("strong");title.textContent=String(t.name||"Verified mission");
    var desc=document.createElement("small");desc.textContent=String(t.desc||"Complete the task to earn points");
    var reward=document.createElement("em");
    var progress=t.target?(" · "+fmt(t.progress||0)+"/"+fmt(t.target)+" VERIFIED"):"";
    reward.textContent="+"+fmt(t.reward)+" ZNQY POINTS · "+(done?"REWARDED":verified?"CHECK MEMBERSHIP":unlocked?"READY TO CLAIM":"COMPLETE TO UNLOCK")+(!done&&!verified?progress:"");
    info.append(title,desc,reward);
    if(link&&verified&&!done){
      var go=document.createElement("a");go.className="mission-channel-link";go.href=link;
      go.target="_blank";go.rel="noopener noreferrer";go.textContent="OPEN CHANNEL";
      info.appendChild(go);
    }
    var button=document.createElement("button");button.type="button";button.className="mission-btn";
    button.dataset.claimTask=t.id;
    button.disabled=!claimable;
    button.textContent=done?"DONE ✓":claimable?(verified?"VERIFY":"CLAIM"):unlocked?"CONNECT":"LOCKED";
    item.append(icon,info,button);root.appendChild(item);
  });
  if(!catalog.length){
    var emptyMessage=document.createElement("p");emptyMessage.className="mission-empty";
    emptyMessage.textContent="No active missions. Check back for verified tasks.";
    root.appendChild(emptyMessage);
  }
  $("mission-done").textContent=count;
  $("mission-total").textContent="/ "+catalog.length;
  $("mission-progress").style.width=(catalog.length?count/catalog.length*100:0)+"%";
  $("mission-signal").textContent=count+"/"+catalog.length+" COMPLETE";
  $("earn-done").textContent=count+"/"+catalog.length;
  $("quick-tasks").textContent=count+" / "+catalog.length+" COMPLETED";
  $("earn-farm").textContent=fmt(state.farmCount);
  $("earn-daily").textContent=(!state.lastDaily||now()-state.lastDaily>=DAILY_MS)?"READY":"CLAIMED";
}
function safeMissionLink(value){
  if(typeof value!=="string"||!/^https:\/\/t\.me\/[A-Za-z][A-Za-z0-9_]{4,31}\/?$/.test(value))return "";
  return value;
}
function renderActivity(){var entries=state.history||[];var box=$("activity-list");if(!entries.length){box.innerHTML='<div class="activity-empty">No transactions yet. Start farming to create your first reward activity. Your points are not on-chain tokens.</div>';return;}box.innerHTML=entries.slice(0,8).map(function(row){var label=String(row.type||"Reward").replace(/[<>]/g,""),amount=fmt(row.amount);return '<div class="activity-item">'+logoIcon("i-gift")+'<span>'+label+'</span><strong>+'+amount+' PTS</strong></div>';}).join("");}
function renderMiningBoost(){
  var active=Math.max(0,Number(state.activeRefCount)||0);
  var percent=DEMO?Math.min(20,active*2):Math.max(0,Math.min(20,Number(state.miningBoostPercent)||0));
  var reward=DEMO?80+Math.floor((80*percent+50)/100):Math.max(80,Math.min(96,Number(state.nextFarmReward)||80));
  ["home","friends"].forEach(function(location){
    $(location+"-boost-percent").textContent="+"+percent+"%";
    $(location+"-boost-active").textContent=Math.min(10,active)+" / 10";
    $(location+"-boost-reward").innerHTML=fmt(reward)+" <small>PTS / 8H</small>";
    $(location+"-boost-fill").style.width=percent*5+"%";
    $(location+"-boost-meter").setAttribute("aria-valuenow",String(percent));
    $(location+"-boost-hint").textContent=percent>=20
      ?"Maximum +20% mining boost unlocked. Your future farming cycles earn up to 96 points."
      :"Each active friend adds +2% boost after their first real farm claim. Next cycles: "+fmt(reward)+" PTS / 8H.";
  });
}

function safeAvatarURL(value){
  if(typeof value!=="string"||!value||value.length>2048)return "";
  try{
    var url=new URL(value),host=url.hostname.toLowerCase();
    var allowed=host==="t.me"||host==="telegram.org"||host.endsWith(".telegram.org")
      ||host==="telegram-cdn.org"||host.endsWith(".telegram-cdn.org")
      ||host==="cdn-telegram.org"||host.endsWith(".cdn-telegram.org");
    return url.protocol==="https:"&&allowed&&!url.username&&!url.password
      &&!url.hash&&(!url.port||url.port==="443")?url.href:"";
  }catch(e){return "";}
}
function placeAvatar(element,photo,name){
  if(!element)return;
  var url=safeAvatarURL(photo),initial=(String(name||"Z").trim().charAt(0)||"Z").toUpperCase();
  if(element.dataset.avatarSource===url&&element.dataset.avatarInitial===initial&&(!url||element.querySelector("img")))return;
  element.dataset.avatarSource=url;
  element.dataset.avatarInitial=initial;
  element.textContent=initial;
  if(!url)return;
  var img=document.createElement("img");
  img.className="telegram-avatar-photo";
  img.alt=String(name||"Telegram user").slice(0,60)+" profile photo";
  img.referrerPolicy="no-referrer";
  img.loading="lazy";
  img.decoding="async";
  img.addEventListener("error",function(){img.remove();});
  img.src=url;
  element.appendChild(img);
}
function renderNetwork(){
  var ownName=String(state.firstName||"Explorer");
  placeAvatar($("network-self-avatar"),state.photoUrl,ownName);
  placeAvatar($("top-avatar"),state.photoUrl,ownName);
  placeAvatar($("profile-initial"),state.photoUrl,ownName);
  var root=$("network-nodes");
  if(!root)return;
  var people=Array.isArray(state.referralMembers)?state.referralMembers.slice(0,12):[];
  root.replaceChildren();
  root.classList.toggle("network-has-members",people.length>0);
  if(!people.length){
    for(var i=0;i<3;i++){
      var emptyNode=document.createElement("span");
      emptyNode.className="network-empty-node";
      emptyNode.innerHTML=logoIcon("i-friends");
      emptyNode.setAttribute("aria-hidden","true");
      root.appendChild(emptyNode);
    }
    $("network-description").textContent="Your network will grow when friends join through your link.";
    return;
  }
  people.forEach(function(person){
    var card=document.createElement("div");
    card.className="network-person"+(person.active?" network-person-active":"");
    var avatar=document.createElement("div");
    avatar.className="network-person-avatar";
    var name=String(person.firstName||"Explorer").slice(0,60);
    placeAvatar(avatar,person.photoUrl,name);
    var label=document.createElement("div");
    label.className="network-person-name";
    label.textContent=name;
    var status=document.createElement("div");
    status.className="network-person-status";
    status.textContent=person.active?"ACTIVE":"JOINED";
    card.append(avatar,label,status);
    root.appendChild(card);
  });
  var count=Math.max(0,Number(state.refCount)||0),extra=Math.max(0,count-people.length);
  $("network-description").textContent=extra
    ?fmt(people.length)+" recent friends shown · +"+fmt(extra)+" more invited."
    :"Real Telegram friends who joined through your personal invite link.";
}

function renderCyber(){
  $("session-status").textContent=DEMO?"LOCAL DEMO POINTS":accountReady?"TELEGRAM VERIFIED":"SECURE LOGIN REQUIRED";
  var heroChip=document.querySelector(".balance-hero .hero-mini-chip");
  if(heroChip&&heroChip.lastChild&&heroChip.lastChild.nodeType===3){
    heroChip.lastChild.nodeValue=DEMO?" LOCAL DEMO POINTS":" PRE-LAUNCH REWARDS";
  }
  $("referral-code").textContent=DEMO?"Share ZENQORY preview":(referralLink?referralLink.replace(/^https?:\/\/t\.me\//,""):"Connect Telegram to invite");
  $("referral-note").textContent=DEMO?"Preview invite only — no referral rewards are recorded.":!accountReady?"Reconnect Telegram to activate personal invitations.":"A friend counts after signing up via your link. Get 10 bonus points when they finish their first 8-hour farming cycle.";
  $("network-spectrum-count").textContent=fmt(state.refCount)+" INVITED FRIEND"+(state.refCount===1?"":"S");
  $("profile-code").textContent=DEMO?"PREVIEW":accountReady?String(state.id||"").slice(-6):"OFFLINE";
  var count=Math.max(0,Number(state.farmCount)||0),stage=count%5,percentage=100*stage/5;
  $("rank-goal").textContent=stage+" / 5 CYCLES";
  $("rank-fill").style.width=percentage+"%";
  var badges=[["badge-pioneer","badge-pioneer-label",count>=1],["badge-claim","badge-claim-label",count>=1],["badge-connector","badge-connector-label",Number(state.refCount)>=1]];
  badges.forEach(function(item){var node=$(item[0]);node.classList.toggle("unlocked",item[2]);$(item[1]).textContent=item[2]?"EARNED":"LOCKED";});
  var feed=$("home-activity-feed"),entries=Array.isArray(state.history)?state.history.slice(0,3):[];
  if(!entries.length){feed.innerHTML='<div class="signal-entry signal-empty">'+logoIcon("i-spark")+'<span>Your reward activity will appear here after your first claim.</span></div>';}
  else{feed.replaceChildren();entries.forEach(function(row){var el=document.createElement("div");el.className="signal-entry";var ico=document.createElement("span");ico.className="signal-entry-icon";ico.innerHTML=logoIcon("i-spark");var label=document.createElement("span");label.className="signal-entry-label";label.textContent=String(row.type||"Reward");var amount=document.createElement("strong");amount.textContent="+"+fmt(row.amount)+" PTS";el.append(ico,label,amount);feed.appendChild(el);});}
}
function render(){document.querySelectorAll("[data-balance]").forEach(function(node){node.textContent=fmt(state.balance);});var name=String(state.firstName||"Explorer").slice(0,55);$("profile-name").textContent=name;$("profile-initial").textContent=(name[0]||"Z").toUpperCase();$("profile-farms").textContent=fmt(state.farmCount);$("profile-friends").textContent=fmt(state.refCount);$("top-level").textContent=Math.max(1,1+Math.floor((state.farmCount||0)/5));$("profile-member").textContent=DEMO?"PREVIEW MEMBER":accountReady?"TELEGRAM MEMBER #"+String(state.id).slice(-6):"SECURE LOGIN REQUIRED";$("friends-total").textContent=fmt(state.refCount);$("friends-active").textContent=fmt(state.activeRefCount||0);$("friends-points").textContent=fmt(state.refPoints);$("quick-referrals").textContent=fmt(state.refCount)+" FRIENDS JOINED";$("referral-code").textContent=referralLink?referralLink.replace(/^https?:\/\/t\.me\//,""):"Connect Telegram to invite";$("copy-referral").disabled=!referralLink||(!DEMO&&!accountReady);$("invite-button").disabled=!referralLink||(!DEMO&&!accountReady);$("invite-bot-button").disabled=!referralBotLink||!accountReady;$("connection-card").hidden=DEMO||accountReady;$("connection-help").textContent=connectionSummary();$("admin-entry").hidden=!(accountReady&&state.isAdmin);renderFarming();renderMissions();renderActivity();renderCyber();renderMiningBoost();renderNetwork();}
async function startOrClaim(){if(state.farmStart===null){await perform("/farm/start",function(){state.farmStart=now();state.farmReward=Number(state.nextFarmReward)||80;},"Farming activated. Your 8-hour cycle has started.");}else if(now()-state.farmStart>=FARM_MS){var reward=Math.max(80,Math.min(96,Number(state.farmReward)||80));await perform("/farm/claim",function(){state.farmStart=null;state.farmCount+=1;state.balance+=reward;record("Farming reward",reward);},"Success! You claimed "+reward+" ZENQORY points.");}}
function claimDaily(){if(state.lastDaily&&now()-state.lastDaily<DAILY_MS)return;perform("/daily",function(){state.lastDaily=now();state.balance+=20;record("Daily reward",20);},"+20 points added to your rewards balance");}
function claimTask(id){var task=missionCatalog().find(function(t){return t.id===id;});if(!task||state.tasks.indexOf(id)!==-1)return;
if(!missionUnlocked(id)){modal("Mission not completed","Complete the mission's stated requirement before claiming the bonus. Rewards are verified on the server.");return;}
perform("/tasks/"+id,function(){state.tasks.push(id);state.balance+=task.reward;record(task.name,task.reward);},"Verified mission complete! +"+task.reward+" points");}
function share(){if(!referralLink){modal("Open inside Telegram","Your personal invite link appears after opening ZENQORY through your official Telegram Mini App.");return;}if(DEMO)notice("Preview share: bonuses are not tracked yet.");var uri="https://t.me/share/url?url="+encodeURIComponent(referralLink)+"&text="+encodeURIComponent("Join ZENQORY — an early digital rewards community.");try{if(tg&&tg.openTelegramLink)tg.openTelegramLink(uri);else window.open(uri,"_blank","noopener,noreferrer");}catch(e){window.open(uri,"_blank","noopener,noreferrer");}}
function shareBotInvite(){
  if(!accountReady||!referralBotLink)return;
  var uri="https://t.me/share/url?url="+encodeURIComponent(referralBotLink)+"&text="+encodeURIComponent("Join me on ZENQORY! Tap Start, then Launch ZENQORY to begin farming points.");
  try{if(tg&&tg.openTelegramLink)tg.openTelegramLink(uri);else window.open(uri,"_blank","noopener,noreferrer");}
  catch(e){window.open(uri,"_blank","noopener,noreferrer");}
}
async function copyReferral(){if(!referralLink)return;try{await navigator.clipboard.writeText(referralLink);notice("Invite link copied");}catch(e){modal("Your invite link",referralLink);}}

var adminData=null,adminLoading=false,adminMutation=false;
function adminElement(tag,className,label){
  var el=document.createElement(tag);
  if(className)el.className=className;
  if(label!==undefined)el.textContent=String(label);
  return el;
}
function appendAdminLine(root,title,meta,status){
  var line=adminElement("div","admin-data-item");
  var main=adminElement("div","admin-data-main");
  main.append(adminElement("strong","",title),adminElement("small","",meta));
  line.append(main,adminElement("span","admin-data-status",status));
  root.appendChild(line);
}
function renderAdminOverview(){
  if(!adminData||!adminData.admin)return;
  var stats=adminData.stats||{};
  [
    ["admin-stat-users",stats.users],["admin-stat-active",stats.activeFarmers],
    ["admin-stat-invites",stats.invited],["admin-stat-points",stats.outstandingPoints],
    ["admin-stat-farms",stats.farmClaims],["admin-stat-claims",stats.missionClaims]
  ].forEach(function(pair){$(pair[0]).textContent=fmt(pair[1]);});
  var list=$("admin-missions");list.replaceChildren();
  var missions=Array.isArray(adminData.missions)?adminData.missions:[];
  $("admin-mission-count").textContent=missions.length+" TASK"+(missions.length===1?"":"S");
  missions.forEach(function(m){
    var panel=adminElement("article","admin-mission-row"+(m.enabled?"":" admin-mission-paused"));
    var top=adminElement("div","admin-mission-top");
    var title=adminElement("div","admin-mission-title");
    title.append(adminElement("strong","",m.name),adminElement("small","",m.desc));
    var reward=adminElement("div","admin-mission-points","+"+fmt(m.reward)+" PTS");
    top.append(title,reward);panel.appendChild(top);
    var meta=adminElement("div","admin-mission-meta");
    meta.append(
      adminElement("span","",String(m.kind||"").replaceAll("_"," ").toUpperCase()+" · "+fmt(m.target)+" REQUIRED"),
      adminElement("span","",fmt(m.claims)+" CLAIMS"),
      adminElement("span",m.enabled?"admin-live":"admin-paused",m.enabled?"LIVE":"PAUSED")
    );
    panel.appendChild(meta);
    var actions=adminElement("div","admin-mission-actions");
    var toggle=adminElement("button","admin-small-button",m.enabled?"PAUSE MISSION":"RESUME MISSION");
    toggle.type="button";toggle.dataset.adminToggle=m.id;
    var edit=adminElement("button","admin-small-button admin-edit-button","EDIT REWARD & TEXT");
    edit.type="button";edit.dataset.adminEdit=m.id;
    actions.append(toggle,edit);panel.appendChild(actions);
    var editForm=adminElement("form","admin-edit-form");
    editForm.hidden=true;editForm.dataset.adminForm=m.id;
    [
      ["name","Title",m.name,"text"],
      ["description","Description",m.desc,"text"],
      ["points","Reward points",m.reward,"number"]
    ].forEach(function(spec){
      var field=adminElement("label","admin-field");
      field.appendChild(adminElement("span","",spec[1]));
      var inp=document.createElement("input");inp.name=spec[0];inp.type=spec[3];
      inp.value=spec[2];inp.required=true;
      if(spec[0]==="points"){inp.min="1";inp.max="500";inp.step="1";}
      else{inp.minLength=spec[0]==="name"?5:10;inp.maxLength=spec[0]==="name"?80:220;}
      field.appendChild(inp);editForm.appendChild(field);
    });
    var save=adminElement("button","admin-save-button","SAVE CHANGES");
    save.type="submit";editForm.appendChild(save);
    panel.appendChild(editForm);list.appendChild(panel);
  });
  if(!missions.length)list.appendChild(adminElement("p","admin-placeholder","No missions found."));
  var rewards=$("admin-rewards");rewards.replaceChildren();
  (adminData.recentRewards||[]).forEach(function(item){
    var date=new Date(Number(item.at)||0).toLocaleDateString("en-US",{month:"short",day:"numeric"});
    appendAdminLine(rewards,item.name||"Explorer",
      (item.type||"Reward")+" · "+date,"+"+fmt(item.points)+" PTS");
  });
  if(!rewards.children.length)rewards.appendChild(adminElement("p","admin-placeholder","No rewards recorded yet."));
  var users=$("admin-users");users.replaceChildren();
  (adminData.recentUsers||[]).forEach(function(u){
    appendAdminLine(users,u.name||"Explorer",
      "Telegram ID ···"+String(u.id||"").slice(-6)+" · "+fmt(u.farmCount)+" farm claims",
      fmt(u.balance)+" PTS");
  });
  if(!users.children.length)users.appendChild(adminElement("p","admin-placeholder","No members yet."));
  var audits=$("admin-audit");audits.replaceChildren();
  (adminData.audit||[]).forEach(function(entry){
    var date=new Date(Number(entry.at)||0).toLocaleDateString("en-US",{month:"short",day:"numeric"});
    appendAdminLine(audits,(entry.action||"CHANGE").toUpperCase()+" · "+(entry.missionId||""),
      entry.details||"Mission change",date);
  });
  if(!audits.children.length)audits.appendChild(adminElement("p","admin-placeholder","No administrative changes yet."));
}
async function loadAdminOverview(){
  if(!accountReady||!state.isAdmin||adminLoading)return;
  adminLoading=true;
  $("admin-refresh").disabled=true;
  try{
    adminData=await callApi("/admin/overview");
    renderAdminOverview();
  }catch(err){
    notice(err.message||"Unable to load administrator data");
    if(err.status===403){state.isAdmin=false;$("admin-entry").hidden=true;openTab("profile");}
  }finally{adminLoading=false;$("admin-refresh").disabled=false;}
}
async function adminUpdateMission(id,changes){
  if(!accountReady||!state.isAdmin||adminMutation)return;
  adminMutation=true;
  try{
    await callApi("/admin/missions/"+encodeURIComponent(id),"PATCH",changes);
    notice("Mission updated. All changes are recorded.");
    await loadAdminOverview();
    normalize(await callApi("/me"));render();
  }catch(err){notice(err.message||"Mission update failed");}
  finally{adminMutation=false;}
}
function updateAdminFormMode(){
  var channel=$("admin-mission-kind").value==="telegram_channel";
  $("admin-channel-field").hidden=!channel;
  $("admin-mission-channel").required=channel;
  $("admin-mission-target").readOnly=channel;
  if(channel)$("admin-mission-target").value="1";
}
$("admin-entry").addEventListener("click",function(){openTab("admin");});
$("admin-back").addEventListener("click",function(){openTab("profile");});
$("admin-refresh").addEventListener("click",loadAdminOverview);
$("admin-mission-kind").addEventListener("change",updateAdminFormMode);
$("admin-mission-form").addEventListener("submit",async function(event){
  event.preventDefault();
  if(!accountReady||!state.isAdmin||adminMutation)return;
  var kind=$("admin-mission-kind").value;
  var payload={
    name:$("admin-mission-name").value.trim(),
    description:$("admin-mission-description").value.trim(),
    kind:kind,
    target:kind==="telegram_channel"?1:Number($("admin-mission-target").value),
    points:Number($("admin-mission-points").value),
    channel:kind==="telegram_channel"?$("admin-mission-channel").value.trim():""
  };
  if(!Number.isInteger(payload.target)||!Number.isInteger(payload.points)){
    notice("Targets and points must be whole numbers");return;
  }
  adminMutation=true;$("admin-create").disabled=true;
  try{
    await callApi("/admin/missions","POST",payload);
    notice("Verified mission published successfully.");
    $("admin-mission-form").reset();updateAdminFormMode();
    await loadAdminOverview();
    normalize(await callApi("/me"));render();
  }catch(err){notice(err.message||"Mission creation failed");}
  finally{adminMutation=false;$("admin-create").disabled=false;}
});
$("admin-missions").addEventListener("click",function(event){
  var edit=event.target.closest("[data-admin-edit]");
  if(edit){
    var form=edit.closest(".admin-mission-row").querySelector(".admin-edit-form");
    form.hidden=!form.hidden;edit.textContent=form.hidden?"EDIT REWARD & TEXT":"CLOSE EDITOR";return;
  }
  var toggle=event.target.closest("[data-admin-toggle]");
  if(toggle&&adminData&&!adminMutation){
    var mission=(adminData.missions||[]).find(function(m){return m.id===toggle.dataset.adminToggle;});
    if(mission)adminUpdateMission(mission.id,{enabled:!mission.enabled});
  }
});
$("admin-missions").addEventListener("submit",function(event){
  var form=event.target.closest("[data-admin-form]");
  if(!form)return;event.preventDefault();
  if(adminMutation)return;
  var data=new FormData(form),id=form.dataset.adminForm;
  adminUpdateMission(id,{
    name:String(data.get("name")||"").trim(),
    description:String(data.get("description")||"").trim(),
    points:Number(data.get("points"))
  });
});
updateAdminFormMode();

function showInfo(kind){var info={
notification:["Notifications","Farming reminders and major ecosystem updates will appear here as we develop the official Telegram bot."],
settings:["ZENQORY Settings","Account settings, language, safety and help options are available from the Profile tab."],
account:["Account Connection","Check your Telegram login and account status here."],
security:["Security First","Telegram session data is verified on the server. We never need your wallet seed phrase or private keys. Never share them with anyone."],
language:["Language Settings","English is the active language for all ZENQORY screens and bot messages."],
support:["How ZENQORY Works","Start an 8-hour farming cycle, then claim your reward. Each active referred friend unlocks +2% mining boost for future cycles (maximum +20%). A friend is active after a real first farm claim. Missions pay once only after their requirements are verified on our server."],
wallet:["TON Wallet — Coming Later","This release tracks off-chain reward points. TON Connect, deposits, withdrawals and token claims are disabled until secure implementation and review."],
withdraw:["Withdrawals Not Available","ZENQORY points currently have no cash value or withdrawal route. A token launch or exchange listing has not been promised."]
};var item=info[kind]||info.support;modal(item[0],kind==="account"?(connectionSummary()+(accountReady?" Your Telegram ID: "+String(state.id):"")):item[1]);}
$("farm-button").addEventListener("click",startOrClaim);$("daily-card").addEventListener("click",claimDaily);$("mission-list").addEventListener("click",function(event){var btn=event.target.closest("[data-claim-task]");if(btn)claimTask(btn.getAttribute("data-claim-task"));});
document.querySelectorAll("[data-tab]").forEach(function(button){button.addEventListener("click",function(){openTab(button.dataset.tab);});});document.querySelectorAll("[data-go]").forEach(function(node){node.addEventListener("click",function(){openTab(node.dataset.go);});node.addEventListener("keydown",function(e){if(e.key==="Enter")openTab(node.dataset.go);});});
$("avatar-button").addEventListener("click",function(){openTab("profile");});$("settings-button").addEventListener("click",function(){openTab("profile");});$("notification-button").addEventListener("click",function(){showInfo("notification");});$("copy-referral").addEventListener("click",copyReferral);$("invite-button").addEventListener("click",share);$("invite-bot-button").addEventListener("click",shareBotInvite);
$("wallet-connect").addEventListener("click",function(){showInfo("wallet");});$("wallet-withdraw").addEventListener("click",function(){showInfo("withdraw");});
["account","notifications","security","language","support"].forEach(function(item){var btn=$(item+"-setting");if(btn)btn.addEventListener("click",function(){showInfo(item==="notifications"?"notification":item);});});
$("modal-close").addEventListener("click",closeModal);$("modal-ok").addEventListener("click",closeModal);$("modal-backdrop").addEventListener("click",function(e){if(e.target===$("modal-backdrop"))closeModal();});document.addEventListener("keydown",function(e){if(e.key==="Escape")closeModal();});
function setConnectionProblem(error){
  accountReady=false;
  var message=String(error&&error.message||"");
  var description=/expired/i.test(message)
    ?"Telegram login expired. Close the Mini App and reopen it from the official ZENQORY bot."
    :/authentication|signature/i.test(message)
    ?"Telegram could not verify your session. Reopen the official bot and confirm BOT_TOKEN belongs to this bot."
    :error&&error.status===503
    ?"Secure reward storage is unavailable. Please try again shortly."
    :"The secure rewards service is temporarily unavailable. Retry your Telegram connection.";
  sessionGuide("Secure login",description);
  busy=false;render();
}
async function loginTelegram(){
  if(DEMO)return;
  if(!tg||!tg.initData){setConnectionProblem(new Error("Missing Telegram initData"));return;}
  busy=true;render();
  try{
    var verified=await callApi("/telegram/verify","POST");
    telegramVerified=true;
    if(verified&&verified.first_name)state.firstName=String(verified.first_name).slice(0,60);
    var snapshot=await callApi("/me","GET");
    normalize(snapshot);accountReady=true;DEMO=false;lastRefreshAt=now();hideSessionGuide();busy=false;render();
    notice("Your secure Telegram rewards account is connected.");
  }catch(error){setConnectionProblem(error);}
}
$("retry-login").addEventListener("click",loginTelegram);
document.addEventListener("visibilitychange",function(){if(document.visibilityState==="visible")refreshLiveState();});
if(DEMO){
  loadPreview();
  sessionGuide("Interactive preview","This browser shows local demo points only. Open the official ZENQORY Telegram Mini App for a secure rewards account.");
}else{
  if(tg&&tg.initDataUnsafe&&tg.initDataUnsafe.user)state.firstName=tg.initDataUnsafe.user.first_name||"Explorer";
  // Do not call bot diagnostics on every open; signed account loading is enough.
  loginTelegram();
}
setInterval(function(){renderFarming();if(tab==="earn")$("earn-daily").textContent=(!state.lastDaily||now()-state.lastDaily>=DAILY_MS)?"READY":"CLAIMED";},1000);
})();
