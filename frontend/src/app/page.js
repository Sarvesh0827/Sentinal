"use client";

import { useEffect, useState, useRef, useMemo } from "react";
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, Legend,
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis
} from "recharts";
import { AlertCircle, CheckCircle2, ShieldAlert, Activity, RefreshCw, Terminal, Zap, Fingerprint, HelpCircle, Database, Shield, X, Info, FileText, Bell, Lock } from "lucide-react";

// Tooltip Component
const InfoTooltip = ({ text }) => (
  <div className="group relative inline-block ml-1 cursor-help">
    <HelpCircle className="w-3.5 h-3.5 text-neutral-500 hover:text-blue-400 transition-colors" />
    <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover:block w-48 p-2 bg-neutral-800 text-neutral-200 text-[10px] rounded border border-neutral-700 shadow-xl z-50 normal-case tracking-normal">
      {text}
      <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-neutral-800"></div>
    </div>
  </div>
);

export default function Dashboard() {
  const [agents, setAgents] = useState({});
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [events, setEvents] = useState([]);
  const [cryptoLog, setCryptoLog] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [showWebhookModal, setShowWebhookModal] = useState(false);
  const [showLedgerModal, setShowLedgerModal] = useState(false);
  const [globalStats, setGlobalStats] = useState({ eventsSeen: 0, threatsBlocked: 0, startTime: Date.now() });
  const [webhookUrl, setWebhookUrl] = useState("");
  const [ledgerData, setLedgerData] = useState([]);
  const [agentTab, setAgentTab] = useState("telemetry"); // 'telemetry' or 'report'

  useEffect(() => {
    // Fetch initial status
    fetch("http://localhost:8000/status")
      .then(res => res.json())
      .then(data => {
        const initialAgents = {};
        data.agents.forEach(a => {
          initialAgents[a.agent_id] = { id: a.agent_id, frozen: a.frozen, lastScore: 0, trustScore: 1.0, history: [], latestFeatures: null, lastReason: a.freeze_reasons?.[0] };
        });
        setAgents(initialAgents);
        setGlobalStats(prev => ({ ...prev, threatsBlocked: data.frozen_count || 0 }));
        if (data.agents.length > 0) setSelectedAgent(data.agents[0].agent_id);
      })
      .catch(err => console.error("Failed to fetch status:", err));

    fetch("http://localhost:8000/webhook")
      .then(res => res.json())
      .then(data => setWebhookUrl(data.url || ""));

    // Connect to SSE stream
    const eventSource = new EventSource("http://localhost:8000/stream");
    
    eventSource.onmessage = (event) => {
      try {
        const decision = JSON.parse(event.data);
        const timestamp = new Date(decision.timestamp).toLocaleTimeString();
        
        // Update global stats
        setGlobalStats(prev => ({
          ...prev,
          eventsSeen: prev.eventsSeen + 1,
          threatsBlocked: decision.decision === "FREEZE" ? prev.threatsBlocked + 1 : prev.threatsBlocked
        }));

        // Add to Matrix Cryptographic Feed
        const sigStatus = decision.decision === "FREEZE" && decision.reasons.some(r => r.includes("invalid_signature")) 
                          ? "CRITICAL: INVALID ED25519 SIGNATURE" 
                          : "ED25519 SIGNATURE VERIFIED";
        const sigColor = decision.decision === "FREEZE" && decision.reasons.some(r => r.includes("invalid_signature")) 
                          ? "text-red-500" 
                          : "text-emerald-500";
        
        setCryptoLog(prev => [...prev, {
          time: timestamp,
          agent: decision.agent_id,
          msg: sigStatus,
          color: sigColor
        }].slice(-50));

        setAgents(prev => {
          const agentId = decision.agent_id;
          const currentAgent = prev[agentId] || { id: agentId, frozen: false, history: [] };
          
          const newHistory = [...currentAgent.history, {
            time: timestamp,
            anomaly: decision.anomaly_score,
            trust: decision.trust_score !== undefined ? decision.trust_score : 1.0
          }].slice(-50);

          return {
            ...prev,
            [agentId]: {
              ...currentAgent,
              frozen: currentAgent.frozen || decision.decision === "FREEZE",
              lastScore: decision.anomaly_score,
              trustScore: decision.trust_score !== undefined ? decision.trust_score : 1.0,
              history: newHistory,
              latestFeatures: decision.features || currentAgent.latestFeatures,
              lastReason: decision.reasons?.length > 0 ? decision.reasons[0] : currentAgent.lastReason
            }
          };
        });

        setEvents(prev => [decision, ...prev].slice(0, 100));
      } catch (err) {
        console.error("Failed to parse SSE event", err);
      }
    };

    return () => eventSource.close();
  }, []);

  const handleUnfreeze = async (agentId) => {
    try {
      await fetch(`http://localhost:8000/unfreeze/${agentId}`, { method: "POST" });
      setAgents(prev => ({
        ...prev,
        [agentId]: { ...prev[agentId], frozen: false, lastReason: null }
      }));
      setAgentTab("telemetry");
    } catch (e) {
      console.error("Unfreeze failed", e);
    }
  };

  const simulateAttack = async (type) => {
    if (!selectedAgent) return;
    
    // Simulate API calls for attack types
    const payloads = [];
    if (type === "rapid_exfil") {
      for(let i=0; i<6; i++) {
        payloads.push({
          agent_id: selectedAgent,
          action_type: "transfer",
          merchant: `unknown_wallet_${i}`,
          amount: 500.0,
        });
      }
    } else if (type === "forgery") {
      payloads.push({
        agent_id: selectedAgent,
        action_type: "transfer",
        merchant: "hacker_wallet",
        amount: 9999.0,
        signature: "INVALID_BASE64_SIG_FORGERY_ATTEMPT_1234==" // Bad signature
      });
    }

    for (let payload of payloads) {
      fetch("http://localhost:8000/act", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).catch(err => console.error(err));
      await new Promise(r => setTimeout(r, 100)); // slight delay between bursts
    }
  };

  const saveWebhook = async () => {
    await fetch("http://localhost:8000/webhook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: webhookUrl })
    });
    setShowWebhookModal(false);
  };

  const openLedger = async () => {
    const res = await fetch("http://localhost:8000/ledger");
    const data = await res.json();
    setLedgerData(data.chain || []);
    setShowLedgerModal(true);
  };

  const selectedAgentData = selectedAgent ? agents[selectedAgent] : null;

  // Format radar data
  const radarData = useMemo(() => {
    if (!selectedAgentData || !selectedAgentData.latestFeatures) return [];
    const f = selectedAgentData.latestFeatures;
    return [
      { subject: "Velocity", A: Math.min(f.spend_velocity / 1000, 1), fullMark: 1 },
      { subject: "Entropy", A: f.action_entropy, fullMark: 2 },
      { subject: "Burst", A: Math.min(f.new_merchant_burst / 5, 1), fullMark: 1 },
      { subject: "Rate", A: Math.min(f.action_rate / 10, 1), fullMark: 1 },
      { subject: "Z-Score", A: Math.min(f.amount_zscore / 10, 1), fullMark: 1 },
    ];
  }, [selectedAgentData]);

  // Compute uptime for events/sec
  const uptimeSecs = Math.max((Date.now() - globalStats.startTime) / 1000, 1);
  const eventsPerSec = (globalStats.eventsSeen / uptimeSecs).toFixed(1);

  // Auto-generate an LLM-style incident report
  const generateReport = () => {
    if (!selectedAgentData || !selectedAgentData.frozen) return "";
    const r = selectedAgentData.lastReason || "";
    if (r.includes("invalid_signature")) {
      return `At ${new Date().toLocaleTimeString()}, Sentinel's KYA (Know-Your-Agent) verification layer intercepted a transaction originating from ${selectedAgentData.id}. The Ed25519 cryptographic signature attached to the payload failed verification. This indicates a high probability that an external actor is attempting to spoof the agent's identity to execute unauthorized actions. The circuit breaker was instantly tripped, blocking the transaction before funds could be exfiltrated.`;
    }
    return `At ${new Date().toLocaleTimeString()}, the Behavioral ML Engine detected severe deviations from ${selectedAgentData.id}'s baseline profile. The anomaly score spiked to ${selectedAgentData.lastScore.toFixed(2)}, heavily weighted by anomalous spend velocity and merchant targeting. This pattern matches the signature of a hijacked agent (e.g., via prompt injection) attempting to rapidly exfiltrate funds to unknown addresses. Sentinel immediately fired the circuit breaker webhook, freezing the agent's wallet access.`;
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 font-sans p-6 overflow-hidden flex flex-col">
      
      {/* "How It Works" Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="bg-neutral-900 border border-neutral-700 rounded-2xl w-full max-w-3xl p-8 relative shadow-2xl">
            <button onClick={() => setShowModal(false)} className="absolute top-4 right-4 text-neutral-400 hover:text-white">
              <X className="w-6 h-6" />
            </button>
            <h2 className="text-2xl font-bold mb-2 flex items-center gap-3">
              <ShieldAlert className="w-6 h-6 text-blue-500" /> Sentinel Architecture
            </h2>
            <p className="text-neutral-400 mb-8">The cryptographic circuit breaker and behavioral firewall for AI agents.</p>
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="bg-neutral-950 p-5 rounded-xl border border-neutral-800 relative overflow-hidden">
                <div className="absolute top-0 right-0 p-4 opacity-5"><Fingerprint className="w-20 h-20" /></div>
                <div className="text-blue-400 font-mono text-xs mb-2">STEP 1</div>
                <h3 className="text-lg font-bold mb-2">Identity (KYA)</h3>
                <p className="text-sm text-neutral-400 leading-relaxed">
                  "Know-Your-Agent". Every transaction must be cryptographically signed using an Ed25519 keypair. We instantly reject forged or spoofed agent actions.
                </p>
              </div>
              <div className="bg-neutral-950 p-5 rounded-xl border border-neutral-800 relative overflow-hidden">
                <div className="absolute top-0 right-0 p-4 opacity-5"><Activity className="w-20 h-20" /></div>
                <div className="text-orange-400 font-mono text-xs mb-2">STEP 2</div>
                <h3 className="text-lg font-bold mb-2">Detection Engine</h3>
                <p className="text-sm text-neutral-400 leading-relaxed">
                  Real-time ML profiles agent behavior. It tracks Spend Velocity, Action Entropy, and Merchant Bursts to detect hallucinations or prompt injections.
                </p>
              </div>
              <div className="bg-neutral-950 p-5 rounded-xl border border-neutral-800 relative overflow-hidden">
                <div className="absolute top-0 right-0 p-4 opacity-5"><Shield className="w-20 h-20" /></div>
                <div className="text-emerald-400 font-mono text-xs mb-2">STEP 3</div>
                <h3 className="text-lg font-bold mb-2">Circuit Breaker</h3>
                <p className="text-sm text-neutral-400 leading-relaxed">
                  If the Anomaly Score exceeds thresholds, Sentinel fires a webhook to automatically freeze the agent's wallet funds before the attack completes.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Webhook Modal */}
      {showWebhookModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
          <div className="bg-neutral-900 border border-neutral-700 rounded-2xl w-full max-w-md p-6 relative shadow-2xl">
            <button onClick={() => setShowWebhookModal(false)} className="absolute top-4 right-4 text-neutral-400 hover:text-white">
              <X className="w-5 h-5" />
            </button>
            <h2 className="text-xl font-bold mb-2 flex items-center gap-2">
              <Bell className="w-5 h-5 text-indigo-400" /> Alert Integrations
            </h2>
            <p className="text-sm text-neutral-400 mb-4">Enter a Discord or Slack Webhook URL to receive live alerts when the circuit breaker trips.</p>
            <input 
              type="text" 
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              placeholder="https://discord.com/api/webhooks/..."
              className="w-full bg-neutral-950 border border-neutral-700 rounded p-2 mb-4 text-sm font-mono text-white focus:outline-none focus:border-indigo-500"
            />
            <button onClick={saveWebhook} className="w-full bg-indigo-600 hover:bg-indigo-500 text-white rounded p-2 text-sm font-bold transition-colors">
              Save Webhook Configuration
            </button>
          </div>
        </div>
      )}

      {/* Ledger Modal */}
      {showLedgerModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="bg-neutral-900 border border-neutral-700 rounded-2xl w-full max-w-5xl max-h-[80vh] flex flex-col relative shadow-2xl">
            <div className="p-6 border-b border-neutral-800 shrink-0">
              <button onClick={() => setShowLedgerModal(false)} className="absolute top-6 right-6 text-neutral-400 hover:text-white">
                <X className="w-6 h-6" />
              </button>
              <h2 className="text-xl font-bold flex items-center gap-2">
                <Lock className="w-5 h-5 text-emerald-500" /> Cryptographic Compliance Ledger
              </h2>
              <p className="text-sm text-neutral-400 mt-1">An immutable, hash-chained audit log of all automated security decisions for regulatory compliance.</p>
            </div>
            <div className="overflow-y-auto p-6 flex-grow custom-scrollbar">
              {ledgerData.length === 0 ? (
                <div className="text-center text-neutral-500 py-10 font-mono">NO BLOCKS IN LEDGER</div>
              ) : (
                <div className="flex flex-col gap-4 font-mono text-xs">
                  {ledgerData.map((block, i) => (
                    <div key={i} className="bg-neutral-950 border border-neutral-800 p-4 rounded-lg relative">
                      <div className="absolute top-4 right-4 text-neutral-600">Block {block.seq}</div>
                      <div className="grid grid-cols-12 gap-4">
                        <div className="col-span-12 md:col-span-4 text-emerald-400/80 break-all">
                          <span className="text-neutral-500 block mb-1">PREVIOUS HASH</span>
                          {block.prev_hash}
                        </div>
                        <div className="col-span-12 md:col-span-4 text-neutral-300">
                          <span className="text-neutral-500 block mb-1">RECORD PAYLOAD</span>
                          <div>Agent: <span className="text-blue-400">{block.record.agent_id}</span></div>
                          <div>Action: <span className="text-red-400">{block.record.decision}</span></div>
                          <div className="text-neutral-500 truncate">Time: {block.record.timestamp}</div>
                        </div>
                        <div className="col-span-12 md:col-span-4 text-emerald-400 font-bold break-all">
                          <span className="text-neutral-500 block mb-1 font-normal">BLOCK HASH</span>
                          {block.hash}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <header className="mb-6 flex items-center justify-between border-b border-neutral-800 pb-4 shrink-0">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-8 h-8 text-blue-500" />
          <h1 className="text-2xl font-bold tracking-tight">Sentinel <span className="text-blue-500 font-light">Command</span></h1>
        </div>
        
        {/* Global Stats Bar */}
        <div className="hidden lg:flex items-center gap-6 text-sm">
          <div className="flex flex-col">
            <span className="text-neutral-500 text-xs font-semibold uppercase">Total Agents</span>
            <span className="font-mono text-lg">{Object.keys(agents).length}</span>
          </div>
          <div className="h-8 w-px bg-neutral-800"></div>
          <div className="flex flex-col">
            <span className="text-neutral-500 text-xs font-semibold uppercase">Threats Blocked</span>
            <span className="font-mono text-lg text-red-400">{globalStats.threatsBlocked}</span>
          </div>
          <div className="h-8 w-px bg-neutral-800"></div>
          <div className="flex flex-col">
            <span className="text-neutral-500 text-xs font-semibold uppercase">Events / Sec</span>
            <span className="font-mono text-lg text-emerald-400">{eventsPerSec}</span>
          </div>
        </div>

        <div className="flex gap-3 items-center">
          <button 
            onClick={() => setShowWebhookModal(true)}
            className="text-xs flex items-center gap-2 text-neutral-400 hover:text-white transition-colors border border-neutral-800 px-3 py-1.5 rounded bg-neutral-900"
          >
            <Bell className="w-3.5 h-3.5 text-indigo-400" /> Live Alerts
          </button>
          <button 
            onClick={openLedger}
            className="text-xs flex items-center gap-2 text-neutral-400 hover:text-white transition-colors border border-neutral-800 px-3 py-1.5 rounded bg-neutral-900"
          >
            <Lock className="w-3.5 h-3.5 text-emerald-400" /> Audit Ledger
          </button>
          <button 
            onClick={() => setShowModal(true)}
            className="text-xs flex items-center gap-2 text-neutral-400 hover:text-white transition-colors border border-neutral-800 px-3 py-1.5 rounded bg-neutral-900"
          >
            <Info className="w-3.5 h-3.5" /> How It Works
          </button>
          <div className="px-3 py-1.5 bg-neutral-900 rounded border border-neutral-800 flex items-center gap-2 ml-2">
            <Activity className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
            <span className="text-xs font-mono text-neutral-400">STREAM_ACTIVE</span>
          </div>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 flex-grow min-h-0">
        
        {/* Left Column: Agents List */}
        <div className="col-span-1 flex flex-col gap-4 min-h-0">
          <h2 className="text-lg font-semibold text-neutral-300 shrink-0">Active Agents</h2>
          <div className="flex flex-col gap-2 overflow-y-auto pr-2 custom-scrollbar">
            {Object.values(agents).map(agent => (
              <div 
                key={agent.id}
                onClick={() => { setSelectedAgent(agent.id); setAgentTab("telemetry"); }}
                className={`p-4 rounded-xl border transition-all cursor-pointer ${
                  selectedAgent === agent.id 
                    ? "border-blue-500 bg-neutral-900 shadow-[0_0_15px_rgba(59,130,246,0.15)]" 
                    : "border-neutral-800 bg-neutral-900/50 hover:bg-neutral-900 hover:border-neutral-700"
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono font-medium">{agent.id}</span>
                  {agent.frozen ? (
                    <span className="flex items-center gap-1 text-[10px] font-bold text-red-400 bg-red-400/10 px-2 py-1 rounded-full animate-pulse">
                      <AlertCircle className="w-3 h-3" /> FROZEN
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-400/10 px-2 py-1 rounded-full">
                      <CheckCircle2 className="w-3 h-3" /> OK
                    </span>
                  )}
                </div>
                <div className="w-full bg-neutral-950 rounded-full h-1.5 mt-3 border border-neutral-800">
                  <div className={`h-1.5 rounded-full ${agent.lastScore > 0.7 ? "bg-red-500" : "bg-emerald-500"}`} style={{ width: `${Math.min(agent.lastScore * 100, 100)}%` }}></div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Middle Column: Details & Radar */}
        <div className="col-span-1 lg:col-span-2 flex flex-col gap-6 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
          {selectedAgentData ? (
            <>
              {/* Agent Detail Header */}
              <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 relative overflow-hidden shrink-0">
                <div className={`absolute top-0 left-0 w-full h-1 bg-gradient-to-r ${selectedAgentData.frozen ? 'from-red-600 to-red-400' : 'from-blue-600 to-emerald-500'} opacity-50`}></div>
                <div className="flex justify-between items-start">
                  <div>
                    <h2 className="text-2xl font-mono font-bold text-white flex items-center gap-2">
                      <Fingerprint className="w-6 h-6 text-blue-400" />
                      {selectedAgentData.id}
                    </h2>
                    <div className="flex gap-4 mt-3">
                      <button onClick={() => setAgentTab("telemetry")} className={`text-sm font-medium pb-1 border-b-2 transition-colors ${agentTab === "telemetry" ? "border-blue-500 text-blue-400" : "border-transparent text-neutral-500 hover:text-neutral-300"}`}>Real-Time Telemetry</button>
                      <button onClick={() => setAgentTab("report")} className={`text-sm font-medium pb-1 border-b-2 transition-colors ${agentTab === "report" ? "border-blue-500 text-blue-400" : "border-transparent text-neutral-500 hover:text-neutral-300"} flex items-center gap-1`}>
                        <FileText className="w-3.5 h-3.5" /> AI Incident Report
                        {selectedAgentData.frozen && <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse ml-1"></span>}
                      </button>
                    </div>
                  </div>
                  {selectedAgentData.frozen && (
                    <button 
                      onClick={() => handleUnfreeze(selectedAgentData.id)}
                      className="flex items-center gap-2 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 px-4 py-2 rounded-lg transition-colors text-sm border border-neutral-700 shadow-lg hover:shadow-emerald-500/20"
                    >
                      <RefreshCw className="w-4 h-4" /> Unfreeze
                    </button>
                  )}
                </div>
              </div>

              {agentTab === "telemetry" ? (
                <>
                  {/* Radar & Multi-Axis Data */}
                  <div className="grid grid-cols-2 gap-6 shrink-0 h-[300px]">
                    <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex flex-col items-center justify-center relative">
                      <h3 className="absolute top-4 left-4 text-xs font-semibold text-neutral-500 uppercase tracking-wider flex items-center">
                        Anomaly Vector Shape <InfoTooltip text="Visualizes 5 dimensions of agent behavior. When an attack occurs, this shape warps outward on specific axes like Velocity (speed of spend) or Burst (targeting new merchants)." />
                      </h3>
                      <ResponsiveContainer width="100%" height="100%">
                        <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
                          <PolarGrid stroke="#262626" />
                          <PolarAngleAxis dataKey="subject" tick={{ fill: '#737373', fontSize: 10 }} />
                          <PolarRadiusAxis angle={30} domain={[0, 1]} tick={false} axisLine={false} />
                          <Radar name="Anomaly Vector" dataKey="A" stroke={selectedAgentData.frozen ? "#ef4444" : "#3b82f6"} fill={selectedAgentData.frozen ? "#ef4444" : "#3b82f6"} fillOpacity={selectedAgentData.frozen ? 0.5 : 0.2} />
                          <RechartsTooltip contentStyle={{ backgroundColor: "#171717", borderColor: "#262626" }} />
                        </RadarChart>
                      </ResponsiveContainer>
                    </div>
                    <div className="flex flex-col gap-4">
                      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex-1 flex flex-col justify-center relative overflow-hidden">
                        <div className="absolute top-0 right-0 p-4 opacity-10">
                          <ShieldAlert className="w-16 h-16" />
                        </div>
                        <div className="text-neutral-500 text-xs uppercase tracking-wider mb-1 flex items-center">
                          Current Anomaly Score <InfoTooltip text="Combined ML and Rules-Engine score representing the probability that this agent's current action is malicious. Threshold > 0.7 triggers a Freeze." />
                        </div>
                        <div className={`text-5xl font-mono ${selectedAgentData.lastScore > 0.7 ? "text-red-500" : "text-emerald-400"}`}>
                          {selectedAgentData.lastScore.toFixed(3)}
                        </div>
                      </div>
                      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex-1 flex flex-col justify-center relative overflow-hidden">
                         <div className="absolute top-0 right-0 p-4 opacity-10">
                          <CheckCircle2 className="w-16 h-16" />
                        </div>
                        <div className="text-neutral-500 text-xs uppercase tracking-wider mb-1 flex items-center">
                          Network Trust Score <InfoTooltip text="A rolling reputation score. It slowly increases as the agent behaves normally, but slashes quickly if anomalies are detected." />
                        </div>
                        <div className={`text-5xl font-mono ${selectedAgentData.trustScore < 0.5 ? "text-red-500" : "text-blue-400"}`}>
                          {(selectedAgentData.trustScore * 100).toFixed(0)}<span className="text-2xl text-neutral-600">%</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Line Chart */}
                  <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-6 shrink-0 h-[300px]">
                    <h3 className="text-xs font-semibold text-neutral-500 mb-4 uppercase tracking-wider">Historical Telemetry</h3>
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={selectedAgentData.history} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#262626" vertical={false} />
                        <XAxis dataKey="time" stroke="#525252" fontSize={10} tickMargin={10} />
                        <YAxis yAxisId="left" domain={[0, 1]} stroke="#525252" fontSize={10} />
                        <RechartsTooltip 
                          contentStyle={{ backgroundColor: "#171717", borderColor: "#262626", color: "#f5f5f5" }}
                          itemStyle={{ color: "#f5f5f5" }}
                        />
                        <Line yAxisId="left" type="monotone" name="Anomaly Score" dataKey="anomaly" stroke="#f97316" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </>
              ) : (
                /* AI Incident Report Tab */
                <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-8 shrink-0 h-[624px] flex flex-col relative overflow-hidden">
                  <div className="absolute -right-10 -top-10 opacity-5"><FileText className="w-64 h-64" /></div>
                  <h3 className="text-xl font-bold text-white mb-6 border-b border-neutral-800 pb-4 flex items-center gap-3">
                    <Zap className="w-5 h-5 text-indigo-400" /> Auto-Generated Security Report
                  </h3>
                  {selectedAgentData.frozen ? (
                    <div className="flex-grow flex flex-col">
                      <div className="bg-red-950/30 border border-red-900/50 rounded-lg p-4 mb-6">
                        <div className="text-red-400 font-bold mb-1 text-sm flex items-center gap-2"><AlertCircle className="w-4 h-4"/> STATUS: CRITICAL INTERVENTION</div>
                        <div className="text-neutral-300 text-sm">Agent wallet has been automatically frozen by the Sentinel Circuit Breaker.</div>
                      </div>
                      <h4 className="text-sm font-semibold text-neutral-400 mb-2 uppercase tracking-wider">LLM Post-Mortem Analysis</h4>
                      <p className="text-neutral-300 leading-relaxed font-serif text-lg bg-neutral-950 p-6 rounded-lg border border-neutral-800 shadow-inner">
                        {generateReport()}
                      </p>
                    </div>
                  ) : (
                    <div className="flex-grow flex items-center justify-center">
                      <div className="text-center text-neutral-500">
                        <CheckCircle2 className="w-12 h-12 mx-auto mb-3 opacity-20" />
                        <p className="font-mono text-sm">No security incidents detected.</p>
                        <p className="text-xs text-neutral-600 mt-1">Agent is operating within normal parameters.</p>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="h-full flex items-center justify-center border border-dashed border-neutral-800 rounded-xl">
              <p className="text-neutral-500 font-mono text-sm animate-pulse">AWAITING AGENT SELECTION...</p>
            </div>
          )}
        </div>

        {/* Right Column: Matrix Feed & Red Team Controls */}
        <div className="col-span-1 flex flex-col gap-6 min-h-0">
          
          {/* Red Team Simulator */}
          <div className="bg-neutral-900 border border-red-900/50 rounded-xl p-5 shrink-0 relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-1 bg-red-600"></div>
            <h3 className="text-sm font-bold text-red-500 mb-4 flex items-center gap-2">
              <Zap className="w-4 h-4" /> Red Team Simulator
            </h3>
            <p className="text-xs text-neutral-400 mb-4">Target: <span className="font-mono text-white">{selectedAgent || "None"}</span></p>
            <div className="flex flex-col gap-4">
              <div>
                <button 
                  onClick={() => simulateAttack("rapid_exfil")}
                  disabled={!selectedAgent}
                  className="w-full bg-neutral-950 hover:bg-red-950 border border-neutral-800 hover:border-red-800 text-neutral-300 text-xs py-2 px-3 rounded transition-all flex justify-between items-center disabled:opacity-50"
                >
                  <span>Trigger Rapid Exfil</span>
                  <span className="font-mono opacity-50">&gt;_</span>
                </button>
                <p className="text-[10px] text-neutral-500 mt-1 leading-tight">Simulates an agent whose prompt was injected to drain funds to unknown wallets.</p>
              </div>
              
              <div>
                <button 
                  onClick={() => simulateAttack("forgery")}
                  disabled={!selectedAgent}
                  className="w-full bg-neutral-950 hover:bg-red-950 border border-neutral-800 hover:border-red-800 text-neutral-300 text-xs py-2 px-3 rounded transition-all flex justify-between items-center disabled:opacity-50"
                >
                  <span>Simulate Signature Forgery</span>
                  <span className="font-mono opacity-50">&gt;_</span>
                </button>
                <p className="text-[10px] text-neutral-500 mt-1 leading-tight">Simulates a hacker trying to spoof this agent without its private Ed25519 key.</p>
              </div>
            </div>
          </div>

          {/* Matrix Terminal Feed */}
          <div className="bg-black border border-neutral-800 rounded-xl p-4 flex-grow flex flex-col min-h-0 relative shadow-[inset_0_0_20px_rgba(0,0,0,0.8)]">
            <h3 className="text-xs font-semibold text-neutral-500 mb-2 flex items-center gap-2 shrink-0">
              <Terminal className="w-4 h-4" /> KYA Cryptographic Feed <InfoTooltip text="Live verification of Ed25519 cryptographic signatures on every single agent action." />
            </h3>
            <div className="flex-grow overflow-y-auto font-mono text-[10px] leading-relaxed custom-scrollbar">
              {[...cryptoLog].reverse().map((log, i) => (
                <div key={i} className="mb-1 opacity-80 hover:opacity-100 transition-opacity">
                  <span className="text-neutral-600">[{log.time}]</span>{" "}
                  <span className="text-blue-400">{log.agent}</span>{" "}
                  <span className={log.color}>{log.msg}</span>
                </div>
              ))}
            </div>
            {/* Scanline effect overlay */}
            <div className="absolute inset-0 pointer-events-none bg-[linear-gradient(rgba(18,16,16,0)_50%,rgba(0,0,0,0.25)_50%),linear-gradient(90deg,rgba(255,0,0,0.06),rgba(0,255,0,0.02),rgba(0,0,255,0.06))] bg-[length:100%_4px,3px_100%] opacity-20"></div>
          </div>

        </div>

      </div>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: #333;
          border-radius: 20px;
        }
      `}</style>
    </div>
  );
}
