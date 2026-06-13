/* =====================================================
   ParkEase — Backend API Connector  v2.0  FIXED
   ===================================================== */

const API = (function() {
  var loc = window.location;
  if (loc.protocol === 'file:') return 'http://localhost:8000';
  if (loc.port === '5500' || loc.port === '5501') return 'http://' + loc.hostname + ':8000';
  return loc.origin;
})();

/* ══ 1. processPayment — saves booking to MongoDB ══*/
function processPayment() {
  var btn   = document.getElementById('payNowBtn');
  var ovl   = document.getElementById('ovl');
  btn.disabled = true;
  if (ovl) ovl.classList.add('on');
  var steps  = ['Connecting...','Verifying details...','Saving booking...','Confirmed!'];
  var si     = 0;
  var stepEl = document.getElementById('ovlStep');
  if (stepEl) stepEl.textContent = steps[0];
  var stepTimer = setInterval(function(){
    si++;
    if (si < steps.length && stepEl) stepEl.textContent = steps[si];
    else clearInterval(stepTimer);
  }, 600);

  var payload = {
    lot_id:         ST.lot.lot_id || ST.lot.id,
    lot_name:       ST.lot.name,
    floor:          ST.floor,
    slot_label:     ST.slot.label.replace(' (Premium)','').trim(),
    is_premium:     ST.slot.premium || false,
    user_name:      ST.uname       || '',
    user_phone:     ST.uphone      || '',
    user_email:     ST.uemail      || '',
    vehicle_number: ST.vnum        || '',
    vehicle_type:   ST.vtype       || '4W',
    vehicle_model:  ST.vmodel      || '',
    entry_time:     ST.entry ? ST.entry.toISOString() : new Date().toISOString(),
    exit_time:      ST.exit  ? ST.exit.toISOString()  : new Date(Date.now()+7200000).toISOString(),
    hours:          ST.hours  || 1,
    total_amount:   ST.total  || 0,
    promo_code:     ST.promoCode || '',
    discount:       ST.discount  || 0,
    payment_method: ST.payMethod || 'card'
  };

  fetch(API + '/api/bookings/create', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  })
  .then(function(r){ return r.json(); })
  .then(function(data){
    clearInterval(stepTimer);
    if (ovl) ovl.classList.remove('on');
    btn.disabled = false;
    if (data.success) {
      ST.bid = data.booking_id;
      showTicket();
      showToast('Booking confirmed!','success');
    } else {
      showToast('Booking failed: '+(data.detail||'Try again'),'error');
      btn.disabled = false;
    }
  })
  .catch(function(){
    clearInterval(stepTimer);
    if (ovl) ovl.classList.remove('on');
    btn.disabled = false;
    showTicket();
    showToast('Saved locally (offline)','info');
  });
}

/* ══ 2. verifyId — verify ticket from MongoDB ══*/
function verifyId() {
  var inp = document.getElementById('verInput').value.trim().toUpperCase();
  var res = document.getElementById('verResult');
  if (!inp) {
    res.innerHTML = '<div class="ver-fail"><p style="color:var(--mu)">Please enter a Booking ID.</p></div>';
    return;
  }
  res.innerHTML = '<div style="text-align:center;padding:30px;color:var(--mu)">&#8987; Verifying...</div>';

  fetch(API + '/api/bookings/' + encodeURIComponent(inp))
    .then(function(r){ return r.json(); })
    .then(function(data){
      if (data.success && data.booking) {
        var b = data.booking;
        var entryDate = new Date(b.entry_time);
        var exitDate  = new Date(b.exit_time);
        var statusColor = b.status==='active' ? 'var(--a)' : b.status==='expired' ? '#ff4d6d' : '#ffd60a';
        res.innerHTML = '<div class="ver-ok">'
          +'<div class="ver-header">'
          +'<div class="ver-check">&#10003;</div>'
          +'<div class="ver-hinfo"><h3>&#9989; Ticket Verified</h3><p>Valid booking confirmed</p></div>'
          +'</div><div class="ver-rows">'
          +vrow('Booking ID','<span style="letter-spacing:2px;color:var(--a)">'+b.booking_id+'</span>')
          +vrow('Status','<span style="color:'+statusColor+';font-weight:700">'+b.status.toUpperCase()+'</span>')
          +vrow('Passenger', b.user_name||'--')
          +vrow('Phone',     b.user_phone||'--')
          +vrow('Location',  b.lot_name)
          +vrow('Floor',     b.floor)
          +vrow('Slot','<span style="color:var(--a)">'+b.slot_label+'</span>')
          +vrow('Vehicle','<span style="color:var(--a2)">'+b.vehicle_type+' | '+b.vehicle_number+'</span>')
          +vrow('Entry', entryDate.toLocaleString('en-IN'))
          +vrow('Exit',  exitDate.toLocaleString('en-IN'))
          +vrow('Amount','Rs.'+b.total_amount)
          +'</div></div>';
      } else {
        // localStorage fallback
        var hist=[]; try{hist=JSON.parse(localStorage.getItem('pe_hist')||'[]');}catch(e){}
        var found=null;
        for(var i=0;i<hist.length;i++){if(hist[i].bid&&hist[i].bid.toUpperCase()===inp){found=hist[i];break;}}
        if(found){
          res.innerHTML = '<div class="ver-ok">'
            +'<div class="ver-header"><div class="ver-check">&#10003;</div>'
            +'<div class="ver-hinfo"><h3>&#9989; Ticket Verified</h3><p>Valid booking confirmed</p></div>'
            +'</div><div class="ver-rows">'
            +vrow('Booking ID','<span style="letter-spacing:2px;color:var(--a)">'+found.bid+'</span>')
            +vrow('Location',found.lot)+vrow('Slot',found.slot)+vrow('Floor',found.floor||'--')
            +vrow('Date',found.date)+vrow('Entry',found.entry)+vrow('Exit',found.exit)
            +vrow('Vehicle',found.veh)+vrow('Amount',found.amt)+vrow('Passenger',found.name||'--')
            +'</div></div>';
        } else {
          res.innerHTML='<div class="ver-fail"><div style="font-size:44px;margin-bottom:14px">&#10060;</div>'
            +'<h3 style="color:#ff4d6d;margin-bottom:8px">Ticket Not Found</h3>'
            +'<p style="color:var(--mu)">Booking ID <strong style="color:var(--tx)">'+inp+'</strong> was not found.</p></div>';
        }
      }
    })
    .catch(function(){
      // Offline fallback
      var hist=[]; try{hist=JSON.parse(localStorage.getItem('pe_hist')||'[]');}catch(e){}
      var found=null;
      for(var i=0;i<hist.length;i++){if(hist[i].bid&&hist[i].bid.toUpperCase()===inp){found=hist[i];break;}}
      if(found){
        res.innerHTML='<div class="ver-ok"><div class="ver-header"><div class="ver-check">&#10003;</div>'
          +'<div class="ver-hinfo"><h3>&#9989; Ticket Verified</h3><p>Local booking</p></div></div>'
          +'<div class="ver-rows">'+vrow('Booking ID',found.bid)+vrow('Location',found.lot)
          +vrow('Slot',found.slot)+vrow('Date',found.date)+vrow('Amount',found.amt)+'</div></div>';
      } else {
        res.innerHTML='<div class="ver-fail"><p style="color:var(--mu)">Cannot connect to server. Check your connection.</p></div>';
      }
    });
}

function vrow(label,val){
  return '<div class="ver-row"><span class="ver-lbl">'+label+'</span><span class="ver-val">'+val+'</span></div>';
}

/* ══ 3. goSearch — load lots from MongoDB ══*/
function goSearch() {
  if(typeof showSkeleton==='function') showSkeleton();
  fetch(API+'/api/lots/city/'+encodeURIComponent(currentCity||'Bengaluru'))
    .then(function(r){return r.json();})
    .then(function(data){
      if(data.success&&data.lots&&data.lots.length){
        lots=data.lots.map(function(l){l.id=l.lot_id;l.avail=l.available_slots;return l;});
        renderLots(lots);
      } else { renderLots(lots); }
      if(typeof hideSkeleton==='function') hideSkeleton();
    })
    .catch(function(){
      if(typeof hideSkeleton==='function') hideSkeleton();
      renderLots(lots);
    });
  goTo('search');
}

/* ══ 4. submitRating — save review to MongoDB ══*/
function submitRating() {
  if(!currentRating){showToast('Please select a star rating','error');return;}
  var text=document.getElementById('reviewText')?document.getElementById('reviewText').value.trim():'';
  var lotId=ST.lot?(ST.lot.lot_id||ST.lot.id):0;

  fetch(API+'/api/reviews/',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lot_id:lotId,lot_name:ST.lot?ST.lot.name:'',stars:currentRating,text:text,user_name:ST.uname||'Anonymous',booking_id:ST.bid||''})
  })
  .finally(function(){
    var form=document.getElementById('ratingForm');
    if(form){form.innerHTML='<div style="text-align:center;padding:20px"><div style="font-size:2.5rem;margin-bottom:10px">&#127775;</div><h4 style="color:var(--a);margin-bottom:6px">Thank you!</h4><p style="font-size:.82rem;color:var(--mu)">Your review has been saved</p></div>';}
    showToast('Review submitted!','success');
    currentRating=0;
  });
}

/* ══ 5. Admin stats from MongoDB ══*/
function renderAdminDash(){
  fetch(API+'/api/admin/stats').then(function(r){return r.json();}).then(function(data){
    if(data.success){
      var s=data.stats;
      document.getElementById('admStats').innerHTML=
        admStat(s.total_bookings,'Total Bookings','var(--a)')+
        admStat('Rs.'+s.total_revenue,'Total Revenue','#ffd60a')+
        admStat(s.today_bookings,'Today Bookings','var(--a2)')+
        admStat(s.active_bookings,'Active Now','#00b4d8')+
        admStat(s.total_lots,'Active Lots','var(--a)')+
        admStat(s.occupancy_rate+'%','Occupancy','#ffd60a');
    }
  }).catch(function(){
    var hist=[];try{hist=JSON.parse(localStorage.getItem('pe_hist')||'[]');}catch(e){}
    var rev=0;hist.forEach(function(h){rev+=parseInt((h.amt||'0').replace(/[^0-9]/g,''))||0;});
    document.getElementById('admStats').innerHTML=
      admStat(hist.length,'Total Bookings','var(--a)')+admStat('Rs.'+rev,'Total Revenue','#ffd60a')+
      admStat(lots.length,'Active Lots','var(--a2)')+admStat(lots.length*24,'Total Slots','var(--w)');
  });

  fetch(API+'/api/admin/bookings?limit=20').then(function(r){return r.json();}).then(function(data){
    if(!data.success)return;
    var bkH='';
    data.bookings.forEach(function(b){
      bkH+='<div style="margin-bottom:10px;padding:12px;background:var(--bg);border-radius:12px;border:1px solid var(--bd)">'
        +'<div style="display:flex;justify-content:space-between;margin-bottom:4px">'
        +'<span style="font-weight:700;font-size:.85rem;color:var(--a)">'+b.booking_id+'</span>'
        +'<span style="font-size:.75rem;color:#ffd60a">Rs.'+b.total_amount+'</span></div>'
        +'<div style="font-size:.78rem;color:var(--mu)">'+b.lot_name+' | Slot '+b.slot_label+' | '+b.user_name+'</div>'
        +'<div style="font-size:.72rem;color:var(--bd);margin-top:2px">'+new Date(b.created_at).toLocaleString('en-IN')+'</div></div>';
    });
    var el=document.getElementById('admBkList');
    if(el) el.innerHTML=bkH||'<p style="color:var(--mu);text-align:center;padding:20px">No bookings yet</p>';
  }).catch(function(){});
}

/* ══ INIT ══*/
document.addEventListener('DOMContentLoaded',function(){
  fetch(API+'/health').then(function(r){return r.json();}).then(function(d){
    console.log('Backend online:',d.status);
  }).catch(function(){
    console.warn('Backend offline - local mode');
  });
});
