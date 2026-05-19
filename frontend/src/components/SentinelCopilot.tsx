import { useState, useRef, useEffect } from 'react';
import { MessageSquare, X, Send, Bot, User, Loader2 } from 'lucide-react';
import { fetchWithAuth } from '../api';
import ReactMarkdown from 'react-markdown';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export default function SentinelCopilot() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([{
    role: 'assistant',
    content: "Ciao! Sono **Sentinel AI**, il tuo Direttore Finanziario Virtuale. Come posso aiutarti oggi?"
  }]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    if (isOpen) scrollToBottom();
  }, [messages, isOpen]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;

    const userMessage: ChatMessage = { role: 'user', content: input.trim() };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput('');
    setLoading(true);

    try {
      const history = newMessages.slice(1); // skip greeting
      
      const response = await fetchWithAuth('/ai/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: userMessage.content,
          history: history
        })
      });

      setMessages([...newMessages, { role: 'assistant', content: response.reply }]);
    } catch (err: any) {
      setMessages([...newMessages, { 
        role: 'assistant', 
        content: `❌ **Errore di connessione.**\n\nNon riesco a raggiungere il server AI. Assicurati che l'API Key sia configurata. Dettagli: ${err.message}` 
      }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {/* Floating Button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          style={{
            position: 'fixed', bottom: '24px', right: '24px', zIndex: 9999,
            width: '60px', height: '60px', borderRadius: '50%',
            background: 'linear-gradient(135deg, var(--accent-blue) 0%, #60a5fa 100%)',
            border: '1px solid rgba(255,255,255,0.2)', color: 'white', 
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 8px 32px rgba(59, 130, 246, 0.4)', cursor: 'pointer',
            transition: 'transform 0.2s',
          }}
          onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.05)'}
          onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
        >
          <MessageSquare size={28} />
        </button>
      )}

      {/* Chat Window */}
      {isOpen && (
        <div style={{
          position: 'fixed', bottom: '24px', right: '24px', zIndex: 9999,
          width: '380px', height: '600px', maxHeight: '80vh',
          background: 'rgba(20, 20, 30, 0.95)', backdropFilter: 'blur(16px)',
          border: '1px solid var(--border-glass)', borderRadius: '16px',
          display: 'flex', flexDirection: 'column',
          boxShadow: '0 20px 40px rgba(0,0,0,0.5)', overflow: 'hidden'
        }}>
          {/* Header */}
          <div style={{
            padding: '16px', background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid var(--border-glass)',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'var(--accent-blue)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Bot size={20} color="white" />
              </div>
              <div>
                <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>Sentinel AI</h3>
                <p style={{ margin: 0, fontSize: '0.75rem', color: '#10b981' }}>● Modello Groq Connesso</p>
              </div>
            </div>
            <button 
              onClick={() => setIsOpen(false)}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
            >
              <X size={20} />
            </button>
          </div>

          {/* Messages Area */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {messages.map((msg, idx) => (
              <div key={idx} style={{
                display: 'flex', gap: '12px',
                flexDirection: msg.role === 'user' ? 'row-reverse' : 'row'
              }}>
                <div style={{
                  width: '28px', height: '28px', borderRadius: '50%', flexShrink: 0,
                  background: msg.role === 'user' ? 'rgba(255,255,255,0.1)' : 'var(--accent-blue)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center'
                }}>
                  {msg.role === 'user' ? <User size={14} color="white" /> : <Bot size={14} color="white" />}
                </div>
                <div style={{
                  maxWidth: '75%', padding: '10px 14px', borderRadius: '12px',
                  background: msg.role === 'user' ? 'rgba(255,255,255,0.1)' : 'rgba(59, 130, 246, 0.15)',
                  border: msg.role === 'assistant' ? '1px solid rgba(59, 130, 246, 0.2)' : '1px solid transparent',
                  color: 'white', fontSize: '0.9rem', lineHeight: '1.4'
                }}>
                  <div style={{ margin: 0, padding: 0 }}>
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                </div>
              </div>
            ))}
            {loading && (
              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ width: '28px', height: '28px', borderRadius: '50%', background: 'var(--accent-blue)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <Bot size={14} color="white" />
                </div>
                <div style={{ padding: '10px 14px', borderRadius: '12px', background: 'rgba(59, 130, 246, 0.15)', border: '1px solid rgba(59, 130, 246, 0.2)', color: 'var(--accent-blue)', display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.9rem' }}>
                  <Loader2 size={16} className="spin" /> Sto analizzando...
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <div style={{ padding: '16px', background: 'rgba(255,255,255,0.02)', borderTop: '1px solid var(--border-glass)', display: 'flex', gap: '8px' }}>
            <input 
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSend()}
              placeholder="Chiedimi qualcosa sui tuoi dati..."
              style={{
                flex: 1, padding: '12px 16px', borderRadius: '24px',
                border: '1px solid var(--border-glass)', background: 'rgba(0,0,0,0.2)',
                color: 'white', outline: 'none', boxSizing: 'border-box'
              }}
            />
            <button
              onClick={handleSend}
              disabled={loading || !input.trim()}
              style={{
                width: '44px', height: '44px', borderRadius: '50%', flexShrink: 0,
                background: input.trim() && !loading ? 'var(--accent-blue)' : 'rgba(255,255,255,0.1)',
                border: 'none', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center',
                cursor: input.trim() && !loading ? 'pointer' : 'not-allowed', transition: 'background 0.2s'
              }}
            >
              <Send size={18} style={{ marginLeft: '2px' }} />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
