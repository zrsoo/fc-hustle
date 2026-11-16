/* Controller dialect 4. Factory receives private document state, never exports selectors. */
(() => {
  'use strict';
  if(window.__fcControllerFactoryV1)return;
  window.__fcControllerFactoryV1=function(s){
    const {keys,hex,num,equal,id,auction,known,reads,helper,bidReceipt,captureBid,finishBid,diagnostic}=s;
    const attempted=new Set(),proofs=new Map();let cancel=null;
    const target=t=>keys(t,'trade_id,item_id,definition_id') && /^trade:[a-f0-9]{24}$/.test(t.trade_id) &&
      /^item:[a-f0-9]{24}$/.test(t.item_id) && num(t.definition_id)>0;
    function valid(c){
      if(!keys(c,'schema,id,operation,params,context,fences') || c.schema!==4 || !hex(c.id) ||
        !s.scope(c.context,c.fences))return false;
      const p=c.params;
      if(['watched','balance'].includes(c.operation))return keys(p,'');
      if(c.operation==='status_batch')return keys(p,'targets') && Array.isArray(p.targets) && p.targets.length>0 && p.targets.length<=10 &&
        p.targets.every(target) && new Set(p.targets.map(t=>t.trade_id)).size===p.targets.length && new Set(p.targets.map(t=>t.item_id)).size===p.targets.length;
      return c.operation==='bid' && keys(p,'target,amount,minimum,cap,deadline,status_read_id,batch_id,decision_id') && target(p.target) &&
        [p.amount,p.minimum,p.cap].every(n=>num(n)>0) && p.amount===p.minimum && p.amount<=p.cap &&
        [p.batch_id,p.decision_id,p.status_read_id].every(hex) && Number.isFinite(Date.parse(p.deadline)) && Date.parse(p.deadline)>Date.now();
    }
    const fresh=at=>Date.now()>=Date.parse(at) && Date.now()-Date.parse(at)<=30000;
    async function retained(t,c){
      const e=known.get(t.trade_id),a=e?.raw.getAuctionData?.();
      if(!e || !a || e.row.item.item_id!==t.item_id || e.row.item.definition_id!==t.definition_id ||
        await id(e.raw.id,'item',c.context.identity_namespace)!==t.item_id || e.raw.definitionId!==t.definition_id ||
        String(a.tradeId)!==e.native_trade_id || await id(a.tradeId,'trade',c.context.identity_namespace)!==t.trade_id)throw Error('known_identity_unavailable');
      return e;
    }
    async function execute(c){
      const out={schema:4,command_id:hex(c?.id)?c.id:'0'.repeat(32),operation:c?.operation,context:c?.context,fences:c?.fences,
        success:false,error:'invalid_command',status:null,network:[],background:[],auctions:[],links:[],missing:[],credits:null,
        receipt:null,observed_at:new Date().toISOString(),network_at:null,designated_account_verified:false};
      if(!valid(c))return out;
      if(!s.acquire()){out.error='bridge_busy';return out;}
      const restorers=[],listeners=[],requests=[],pending=new WeakMap();
      let active=true,invoking=false,sending=false,invocations=0,queueCount=0,bidState=null,observable=null,owner={},timer;
      const restore=()=>{active=false;clearTimeout(timer);try{observable?.unobserve?.(owner);}catch{}
        const queue=services.UTUtasRequestQueue;
        if(Array.isArray(queue?.queue))for(let i=queue.queue.length-1;i>=0;i--)if(requests.includes(queue.queue[i].request))queue.queue.splice(i,1);
        if(!out.success)for(const request of requests){try{request.abort?.();}catch{}}
        for(const [x,f]of listeners)x.removeEventListener?.('loadend',f);
        restorers.reverse().forEach(f=>{try{f();}catch{}});cancel=null;s.release();};
      const wrap=(obj,key,fn)=>{const descriptor=Object.getOwnPropertyDescriptor(obj,key),original=obj[key];obj[key]=fn(original);const replacement=obj[key];restorers.push(()=>{if(obj[key]===replacement){if(descriptor)Object.defineProperty(obj,key,descriptor);else delete obj[key];}});};
      try{
        s.auth();out.designated_account_verified=true;
        let invoke,entries=[];const p=c.params,op=c.operation;
        if(op==='status_batch'){
          entries=await Promise.all(p.targets.map(t=>retained(t,c)));
          invoke=()=>services.Item.transfersDao.getAuctionData(entries.map(e=>e.raw));
        }else if(op==='watched'){
          repositories.Item.setDirty(ItemPile.INBOX);invoke=()=>services.Item.requestWatchedItems();
        }else if(op==='balance')invoke=()=>services.User.requestCurrencies();
        else{
          const e=await retained(p.target,c),proof=proofs.get(p.status_read_id)??reads.get(p.status_read_id),row=proof?.rows?.find(r=>r?.trade_id===p.target.trade_id);
          const action=[c.context.account,p.target.trade_id,p.target.item_id,p.target.definition_id,p.amount,p.decision_id].join('|');
          if(attempted.has(c.id) || attempted.has(action) || !proof || !(proof.operation==='search'?Date.now()>=Date.parse(proof.at):fresh(proof.at)) || !equal(proof.fences,c.fences) ||
            !row || row.item.item_id!==p.target.item_id || row.item.definition_id!==p.target.definition_id || row.trade_state!=='active' ||
            !['none','outbid'].includes(row.bid_state) || row.item.untradeable!==false ||
            Date.parse(p.deadline)>Date.parse(proof.at)+row.expires*1000 || row.buy_now_price>0 && p.amount>=row.buy_now_price ||
            p.minimum!==(row.current_bid===0?row.starting_bid:helper('above',row.current_bid)))throw Error('invalid_preconditions');
          const current=await auction(e.raw,{...c,operation:'status'},null);
          if(current.trade_id!==row.trade_id || current.item.item_id!==row.item.item_id || current.item.definition_id!==row.item.definition_id || current.item.untradeable!==false || current.expires<=0 ||
            current.starting_bid!==row.starting_bid || current.buy_now_price!==row.buy_now_price ||
            current.current_bid!==row.current_bid || current.bid_state!==row.bid_state || current.trade_state!==row.trade_state)throw Error('invalid_preconditions');
          attempted.add(c.id);attempted.add(action);
          bidState={raw:e.raw,before:row,receipt:bidReceipt(),invocations:0,native:null};
          bidState.receipt.before_bid_state=row.bid_state;
          bidState.nativeTrade=e.native_trade_id;out.receipt=bidState.receipt;
          const legacy={...c,params:{...p,...p.target}};
          restorers.push(captureBid(e.raw,p.amount,bidState));
          invoke=()=>services.Item.bid(e.raw,p.amount);out._legacy=legacy;
        }
        const queue=services.UTUtasRequestQueue;
        if(typeof queue?.send!=='function' || !Array.isArray(queue.queue))throw Error('service_unavailable');
        // Tag the actual request object created synchronously by this native call.
        // Queue delay is handled by wrapping only that object's send, not by URL matching.
        wrap(queue,'send',original=>function(request,...args){
          if(invoking){
            if(++queueCount!==1 || typeof request?.send!=='function')throw Error('ambiguous_network');
            requests.push(request);
            // These are settings on this finite request, never global auth policy.
            // Automatic reauthentication/retry must not replay a possible mutation.
            request.doRetry=false;request.doReauth=false;
            wrap(request,'send',send=>function(...more){
              if(!active || !s.scope(c.context,c.fences))throw Error('interrupted');
              s.auth();
              if(op==='bid' && Date.now()>=Date.parse(p.deadline))throw Error('invalid_preconditions');
              // Native retries must never replay an owned request.
              if(++invocations!==1)throw Error('ambiguous_network');
              const previous=sending;sending=true;try{return send.apply(this,more);}finally{sending=previous;}
            });
          }
          return original.call(this,request,...args);
        });
        const proto=XMLHttpRequest.prototype;
        wrap(proto,'open',original=>function(method,url,...args){
          if(!sending){pending.set(this,null);return original.call(this,method,url,...args);}
          let u;try{u=new URL(url,location.href);}catch{throw Error('ambiguous_network');}
          const path=op==='bid'?'/ut/game/fc27/trade/'+bidState.nativeTrade+'/bid':
            '/ut/game/fc27/'+({status_batch:'trade/status/lite',watched:'watchlist',balance:'user/credits'}[op]);
          const query=op==='status_batch'?'?tradeIds='+entries.map(e=>e.native_trade_id).join(','):'';
          // URLSearchParams accounts for percent encoded commas without relaxing keys/order/IDs.
          const queryOK=op==='status_batch'?[...u.searchParams.keys()].join(',')==='tradeIds' &&
            u.searchParams.getAll('tradeIds').length===1 && u.searchParams.get('tradeIds')===query.slice(10):u.search==='';
          if(u.protocol!=='https:' || !/^utas(?:\.[a-z0-9-]{1,20}){1,8}\.ea\.com$/.test(u.hostname) ||
            method!==(op==='bid'?'PUT':'GET') || u.pathname!==path || !queryOK)throw Error('ambiguous_network');
          pending.set(this,{method,path:op==='bid'?'/ut/game/fc27/trade/:trade/bid':path,host:u.hostname,
            targets:op==='status_batch'?p.targets:op==='bid'?[p.target]:[],status:null,session_header_present:false});
          return original.call(this,method,url,...args);
        });
        wrap(proto,'setRequestHeader',original=>function(name,value){const n=pending.get(this);
          if(n && String(name).toLowerCase()==='x-ut-sid')n.session_header_present=true;
          return original.call(this,name,value);
        });
        wrap(proto,'send',original=>function(body){
          const n=pending.get(this);
          if(!n){if(active && out.background.length<32)out.background.push({event:'UNOWNED_SEND'});return original.call(this,body);}
          s.auth();
          if(!active || out.network.length || !n.session_header_present)throw Error('unauthenticated');
          if(op==='bid'){
            let data;try{data=JSON.parse(body);}catch{}
            if(!keys(data,'bid') || data.bid!==p.amount)throw Error('invalid_preconditions');
            Object.assign(bidState.receipt,{wire_identity_matches:true,wire_amount_matches:true,wire_trade_id:p.target.trade_id,wire_amount:p.amount});
          }else if(body!=null && body!=='')throw Error('invalid_preconditions');
          out.network.push(n);out.network_at=new Date().toISOString();
          const f=()=>{if(!active)return;n.status=num(this.status)||null;
            if(op==='bid'){
              try{const data=this.responseType==='json'?this.response:JSON.parse(this.responseType==='arraybuffer'?new TextDecoder().decode(this.response):this.responseText);
                bidState.receipt.wire_item_count=Array.isArray(data?.auctionInfo)?data.auctionInfo.length:null;
                bidState.receipt.wire_error_code=num(data?.code);}catch{}
            }
          };
          listeners.push([this,f]);this.addEventListener('loadend',f,{once:true});return original.call(this,body);
        });
        const response=await new Promise((resolve,reject)=>{
          cancel=()=>reject(Error('interrupted'));
          timer=setTimeout(()=>reject(Error('service_timeout')),15000);
          try{s.auth();invoking=true;observable=invoke();invoking=false;
            if(typeof observable?.observe!=='function')throw Error('service_unavailable');
            // Observable callbacks are never ownership scopes. A background request
            // during delivery cannot become an owned send.
            observable.observe(owner,(sender,r)=>{if(active){try{sender?.unobserve?.(owner);}catch{}resolve(r);}});
          }catch(e){invoking=false;reject(e);}
        });
        s.auth();out.status=num(response?.status);
        if(bidState)await finishBid(bidState,out._legacy);
        if(queueCount!==1 || invocations!==1 || out.network.length!==1 || !out.network[0].session_header_present ||
          out.network[0].status!==out.status || !fresh(out.network_at))throw Error('ambiguous_network');
        if(out.status!==200){if(op==='bid' && out.receipt.verdict==='REJECTED'){out.error='bid_rejected';return out;}throw Error('service_failed');}
        if(response?.success!==true)throw Error('service_failed');
        if(op==='balance'){
          out.credits=num((response.response??response.data)?.credits);if(out.credits===null)throw Error('schema_unrecognized');
        }else if(op!=='bid'){
          const rows=(response.response??response.data)?.items;
          if(!Array.isArray(rows) || rows.length>(op==='status_batch'?10:100))throw Error('schema_unrecognized');
          out.auctions=await Promise.all(rows.map(raw=>auction(raw,{...c,operation:op==='status_batch'?'status':'watched'},out.network_at)));
          if(new Set(out.auctions.map(r=>r.trade_id)).size!==rows.length || new Set(out.auctions.map(r=>r.item.item_id)).size!==rows.length)throw Error('schema_unrecognized');
          if(op==='watched'){
            for(let i=0;i<rows.length;i++){
              const row=out.auctions[i],old=known.get(row.trade_id);
              if(old && (old.row.item.item_id!==row.item.item_id || old.row.item.definition_id!==row.item.definition_id))throw Error('schema_unrecognized');
            }
            for(let i=0;i<rows.length;i++){const row=out.auctions[i];known.set(row.trade_id,{raw:rows[i],row,at:out.network_at,read_id:c.id,native_trade_id:String(rows[i].getAuctionData().tradeId)});}
          }else{
            for(const row of out.auctions){
              const index=p.targets.findIndex(t=>t.trade_id===row.trade_id),t=p.targets[index],e=entries[index];
              if(!t || row.item.item_id!==t.item_id || ![null,0,t.definition_id].includes(row.item.definition_id))throw Error('schema_unrecognized');
              await retained(t,c);
              out.links.push({target:t,full_read_id:e.read_id,full_observed_at:e.at,status_read_id:c.id,
                version_observed:row.item.definition_id!==null && row.item.definition_id!==0,current_dto_matches:false});
            }
            // Keep the full item/version DTO while attaching only the genuine
            // returned auction entity via its official setter. Never synthesize
            // a version or pass a lite item as a full native write target.
            // Validate the entire set before changing any local DTO.
            const updates=out.auctions.map((row,index)=>{
              const e=entries[p.targets.findIndex(t=>t.trade_id===row.trade_id)];
              const a=rows[index].getAuctionData?.();
              if(!a || typeof e.raw.setAuctionData!=='function')throw Error('known_identity_unavailable');
              return {e,a,index};
            });
            s.auth();
            for(const {e,a,index}of updates){
              e.raw.setAuctionData(a);
              if(e.raw.getAuctionData()!==a)throw Error('known_identity_unavailable');
              // A fresh exact terminal status can authorize the existing owned
              // item GET without aging/relabeling the original full-version read.
              e.controller_status={row:{...out.auctions[index],item:{...e.row.item}},at:out.network_at};
              out.links[index].current_dto_matches=true;
            }
            out.missing=p.targets.filter(t=>!out.auctions.some(r=>r.trade_id===t.trade_id));
          }
          const linked=out.auctions.map(row=>{const t=out.links.find(l=>l.target.trade_id===row.trade_id)?.target;
            return t?{...row,item:{...row.item,definition_id:t.definition_id,untradeable:known.get(t.trade_id).row.item.untradeable}}:row;});
          proofs.set(c.id,{at:out.network_at,fences:{...c.fences},rows:linked});
        }
        s.auth();
        if(!s.scope(c.context,c.fences) || !fresh(out.network_at))throw Error('invalid_preconditions');
        if(op==='bid' && out.receipt.verdict!=='ACCEPTED')throw Error('bid_unconfirmed');
        out.success=true;out.error=null;
      }catch(e){
        const errors=['known_identity_unavailable','invalid_preconditions','service_unavailable','service_timeout','interrupted','ambiguous_network','unauthenticated','schema_unrecognized','service_failed','persona_unverified','bid_unconfirmed'];
        out.error=errors.includes(e?.message)?e.message:'internal_error';
        if(out.receipt?.verdict==='ACCEPTED'){out.receipt.verdict='UNCONFIRMED';out.receipt.reason='ENVELOPE_VALIDATION_FAILED';}
      }finally{delete out._legacy;restore();out.observed_at=new Date().toISOString();}
      return out;
    }
    return Object.freeze({execute,interrupt:()=>{cancel?.();},valid});
  };
})();
