import React, { useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowDownLeft, ArrowUpRight, BadgeCheck, Building2, Check, ChevronRight, CircleHelp, Fingerprint, KeyRound, Landmark, LockKeyhole, Menu, Plus, RefreshCw, Shield, ShieldCheck, UserRound, Users, X } from 'lucide-react';
import './styles.css';

const P1 = import.meta.env.VITE_P1_URL || 'http://localhost:8001';
const P2 = import.meta.env.VITE_P2_URL || 'http://localhost:8002';
const moneyDate = (epoch) => new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(epoch * 1000));

function App() {
  const [view, setView] = useState('overview');
  const [registrations, setRegistrations] = useState([]);
  const [token, setToken] = useState('');
  const [loading, setLoading] = useState(false);
  const [bankError, setBankError] = useState('');
  const [notice, setNotice] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState({ full_name: '', email: '', phone: '', account_type: 'Savings' });

  const loadRegistrations = useCallback(async () => {
    if (!token) { setBankError('Enter the bank review token to load customer records.'); return; }
    setLoading(true); setBankError('');
    try {
      const res = await fetch(`${P1}/v1/bank/registrations?limit=100`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not load registrations.');
      setRegistrations(data.registrations || []);
    } catch (error) { setBankError(error.message); }
    finally { setLoading(false); }
  }, [token]);

  useEffect(() => { if (view === 'bank' && token) loadRegistrations(); }, [view]);

  async function submitRegistration(event) {
    event.preventDefault(); setSubmitting(true); setNotice(null);
    try {
      const res = await fetch(`${P2}/v1/register`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ registration: form }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Registration could not be completed.');
      setNotice({ type: 'success', text: `Registration secured. Reference ${data.user_id}` });
      setForm({ full_name: '', email: '', phone: '', account_type: 'Savings' });
    } catch (error) { setNotice({ type: 'error', text: error.message }); }
    finally { setSubmitting(false); }
  }

  const recent = registrations.slice(0, 5);
  const count = registrations.length;
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#top" onClick={() => setView('overview')}><span className="brand-mark"><Activity size={19} strokeWidth={2.5}/></span><span>pricewatchin<span className="brand-dot">.</span><small>SECURE BANKING</small></span></a>
      <div className="workspace-label">WORKSPACE</div>
      <nav className="nav-list">
        <button className={`nav-item ${view === 'overview' ? 'active' : ''}`} onClick={() => setView('overview')}><Activity size={17}/> Overview</button>
        <button className={`nav-item ${view === 'register' ? 'active' : ''}`} onClick={() => setView('register')}><UserRound size={17}/> New registration</button>
        <button className={`nav-item ${view === 'bank' ? 'active' : ''}`} onClick={() => setView('bank')}><Building2 size={17}/> Bank review <span className="nav-count">{count}</span></button>
      </nav>
      <div className="sidebar-bottom"><div className="secure-mini"><span className="secure-icon"><ShieldCheck size={17}/></span><div><strong>Quantum-safe session</strong><small>ML-KEM-768 · AES-256-GCM</small></div><Check size={15} className="green-check"/></div><div className="profile"><div className="avatar">PW</div><div><strong>PriceWatchin Demo</strong><small>Local environment</small></div><Menu size={17}/></div></div>
    </aside>
    <main className="main-content" id="top">
      <header className="topbar"><div className="breadcrumbs">Workspace <ChevronRight size={14}/> <span>{view === 'overview' ? 'Overview' : view === 'register' ? 'New registration' : 'Bank review'}</span></div><div className="top-actions"><span className="environment"><i/> Development</span><button className="icon-button" title="Help"><CircleHelp size={18}/></button></div></header>
      {view === 'overview' && <Overview count={count} recent={recent} go={setView} />}
      {view === 'register' && <Registration form={form} setForm={setForm} submit={submitRegistration} submitting={submitting} notice={notice} go={setView}/>}
      {view === 'bank' && <BankReview token={token} setToken={setToken} records={registrations} error={bankError} loading={loading} refresh={loadRegistrations}/>}
      <footer className="footer"><span>PriceWatchin secure onboarding</span><span><LockKeyhole size={13}/> Protected with post-quantum key exchange</span></footer>
    </main>
  </div>;
}

function Overview({ count, recent, go }) {
  return <div className="page-wrap">
    <div className="page-heading"><div><div className="eyebrow">SUNDAY, NOVEMBER 1, 2026</div><h1>Good morning<span className="heading-period">.</span></h1><p>Your secure onboarding workspace is ready.</p></div><button className="primary-button" onClick={() => go('register')}><Plus size={17}/> New registration</button></div>
    <div className="hero-card"><div className="hero-copy"><div className="hero-pill"><ShieldCheck size={14}/> QUANTUM-READY ONBOARDING</div><h2>A safer start for<br/>every customer.</h2><p>Client identity is verified before a shared secret is established. Customer details travel encrypted from P2 to the bank server.</p><button className="hero-link" onClick={() => go('register')}>Start a registration <ArrowUpRight size={16}/></button></div><div className="hero-art" aria-hidden="true"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="orbit orbit-three"/><div className="art-lock"><LockKeyhole size={30}/></div><span className="float-chip chip-kem"><KeyRound size={15}/> ML-KEM-768</span><span className="float-chip chip-aes"><Shield size={15}/> AES-256-GCM</span><span className="float-chip chip-id"><Fingerprint size={15}/> ID VERIFIED</span></div><div className="hero-index">01 <span>/ 03</span></div></div>
    <div className="metrics-grid"><Metric icon={<Users size={18}/>} label="CUSTOMER RECORDS" value={String(count).padStart(2, '0')} foot="Available to bank review" tone="mint"/><Metric icon={<ShieldCheck size={18}/>} label="ENCRYPTION STATUS" value="Active" foot="Fresh key per registration" tone="lavender"/><Metric icon={<Activity size={18}/>} label="KEY EXCHANGE" value="ML-KEM-768" foot="Authenticated client session" tone="peach"/></div>
    <section className="section-card"><div className="section-head"><div><h3>Recent registrations</h3><p>Latest customer onboarding activity</p></div><button className="text-button" onClick={() => go('bank')}>View bank records <ChevronRight size={15}/></button></div>{recent.length ? <RegistrationTable rows={recent}/> : <div className="empty-state"><div className="empty-icon"><UserRound size={20}/></div><strong>No registrations yet</strong><p>Create a test customer registration to see the secure flow in action.</p><button className="outline-button" onClick={() => go('register')}>Create registration <ArrowUpRight size={15}/></button></div>}</section>
    <div className="flow-strip"><div className="flow-title"><span className="flow-icon"><Activity size={17}/></span><div><strong>How the secure flow works</strong><small>Four steps, one protected session</small></div></div><div className="flow-steps"><FlowStep n="01" label="Verify identities" detail="Ed25519"/><ChevronRight size={15}/><FlowStep n="02" label="Establish secret" detail="ML-KEM-768"/><ChevronRight size={15}/><FlowStep n="03" label="Encrypt data" detail="AES-256-GCM"/><ChevronRight size={15}/><FlowStep n="04" label="Store securely" detail="Redis"/></div></div>
  </div>;
}
function Metric({ icon, label, value, foot, tone }) { return <div className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><div className="metric-label">{label}</div><div className="metric-value">{value}</div><div className="metric-foot"><span className="status-dot"/>{foot}</div></div>; }
function FlowStep({ n, label, detail }) { return <div className="flow-step"><span>{n}</span><strong>{label}</strong><small>{detail}</small></div>; }

function Registration({ form, setForm, submit, submitting, notice, go }) {
  const change = (key) => (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }));
  return <div className="page-wrap narrow-wrap"><div className="page-heading compact-heading"><div><div className="eyebrow">CUSTOMER ONBOARDING</div><h1>New registration<span className="heading-period">.</span></h1><p>Enter the customer's details. P2 will encrypt them before sending to P1.</p></div><div className="secure-tag"><ShieldCheck size={15}/> Encrypted submission</div></div>
    <div className="registration-layout"><form className="form-card" onSubmit={submit}><div className="form-title"><span className="form-icon"><UserRound size={19}/></span><div><h2>Personal details</h2><p>Fields marked with <b>*</b> are required</p></div></div>
      <label>Full name <b>*</b><input required minLength="1" maxLength="120" autoComplete="name" placeholder="e.g. Asha Rao" value={form.full_name} onChange={change('full_name')}/></label>
      <div className="form-row"><label>Email address <b>*</b><input required type="email" autoComplete="email" placeholder="asha@example.com" value={form.email} onChange={change('email')}/></label><label>Phone number <b>*</b><input required minLength="6" maxLength="32" autoComplete="tel" placeholder="+91 98765 43210" value={form.phone} onChange={change('phone')}/></label></div>
      <label>Account type <b>*</b><select value={form.account_type} onChange={change('account_type')}><option>Savings</option><option>Current</option><option>Salary</option></select></label>
      {notice && <div className={`notice ${notice.type}`}>{notice.type === 'success' ? <BadgeCheck size={17}/> : <X size={17}/>}<span>{notice.text}</span></div>}
      <div className="form-actions"><span><LockKeyhole size={14}/> Encrypted end-to-end between P2 and P1</span><button className="primary-button" disabled={submitting}>{submitting ? <><span className="spinner"/> Securing...</> : <>Submit securely <ArrowUpRight size={16}/></>}</button></div>
    </form><aside className="info-card"><div className="info-art"><div className="info-ring"><ShieldCheck size={24}/></div><div className="info-orbit"/></div><span className="eyebrow">YOUR DATA, PROTECTED</span><h3>Secure by design.</h3><p>A new ML-KEM shared secret is created for every submission. Your details are encrypted with AES-GCM before they leave this client.</p><div className="info-rule"/><div className="info-line"><span><Fingerprint size={15}/></span><div><b>Identity verified</b><small>Ed25519 client signature</small></div></div><div className="info-line"><span><KeyRound size={15}/></span><div><b>Session key derived</b><small>HKDF-SHA-256</small></div></div></aside></div>
    <button className="back-link" onClick={() => go('overview')}><ArrowDownLeft size={15}/> Back to overview</button></div>;
}

function BankReview({ token, setToken, records, error, loading, refresh }) {
  return <div className="page-wrap"><div className="page-heading"><div><div className="eyebrow">BANK OPERATIONS</div><h1>Customer records<span className="heading-period">.</span></h1><p>Review customer registrations received by P1.</p></div><button className="outline-button" onClick={refresh} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''}/> Refresh</button></div>
    <div className="admin-gate"><div className="admin-lock"><LockKeyhole size={17}/></div><div className="admin-copy"><strong>Bank review access</strong><span>Enter the BANK_ADMIN_TOKEN configured on P1.</span></div><input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Bank admin token" onKeyDown={(e) => e.key === 'Enter' && refresh()}/><button className="dark-button" onClick={refresh} disabled={loading}>{loading ? 'Loading…' : 'Load records'}</button></div>
    {error && <div className="notice error bank-error"><X size={17}/><span>{error}</span></div>}
    <div className="section-card bank-table-card"><div className="section-head"><div><h3>All registrations <span className="table-count">{records.length}</span></h3><p>Personal information stored in the bank Redis cache</p></div><span className="live-label"><i/> LIVE VIEW</span></div>{records.length ? <RegistrationTable rows={records}/> : <div className="empty-state"><div className="empty-icon"><Landmark size={20}/></div><strong>{loading ? 'Loading records…' : 'No records loaded'}</strong><p>Authenticate with the bank review token to view customer registrations.</p></div>}</div>
    <div className="bank-note"><Shield size={16}/><span><b>Bank perspective:</b> records are decrypted only at P1 after AES-GCM authentication, then written to Redis. This demo endpoint requires a bearer token; use TLS and proper staff authorization before deployment.</span></div>
  </div>;
}

function RegistrationTable({ rows }) {
  return <div className="table-scroll"><table><thead><tr><th>CUSTOMER</th><th>EMAIL</th><th>ACCOUNT</th><th>REGISTERED</th><th>STATUS</th></tr></thead><tbody>{rows.map((r) => <tr key={r.user_id}><td><div className="customer-cell"><span className="customer-avatar">{(r.full_name || '?').split(/\s+/).map(x => x[0]).join('').slice(0, 2).toUpperCase()}</span><span><b>{r.full_name}</b><small>Ref. {r.user_id}</small></span></div></td><td>{r.email}</td><td><span className="account-pill">{r.account_type}</span></td><td>{moneyDate(r.created_at)}</td><td><span className="registered-status"><Check size={12}/> Registered</span></td></tr>)}</tbody></table></div>;
}

createRoot(document.getElementById('root')).render(<App/>);
