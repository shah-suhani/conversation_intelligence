import React, { useState, useEffect, useRef } from 'react';
import { generateAnswer } from './services/Service';
import { Message, Source, ChatSession } from './types';
import { ArrowRightIcon, PlusIcon, LibraryIcon, GlobeIcon, SparkleIcon, SunIcon, MoonIcon } from './components/Icons';
import { SourceCard } from './components/SourceCard';
import { EvidenceOverlay } from './components/EvidenceOverlay';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { HeroGraphic } from './components/HeroGraphic';

const CopyButton = ({ text }: { text: string }) => {
  const [isCopied, setIsCopied] = useState(false);

  const handleCopy = async () => {
    if (!navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(text);
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  };

  return (
    <button
      onClick={handleCopy}
      className={`flex items-center gap-2 text-xs font-medium transition-colors ${isCopied ? 'text-emerald-400' : 'text-perplexity-muted hover:text-perplexity-accent'
        }`}
      title="Copy to clipboard"
    >
      {isCopied ? (
        <>
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
          Copied
        </>
      ) : (
        <>
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          Copy
        </>
      )}
    </button>
  );
};

const HistorySkeleton = () => (
  <div className="animate-in fade-in duration-500 space-y-12">
    {[1].map((_, i) => (
      <div key={i}>
        {/* Title Skeleton */}
        <div className="mb-8 space-y-3">
          <div className="h-8 bg-perplexity-border rounded-lg w-3/4 animate-pulse"></div>
          <div className="h-8 bg-perplexity-border rounded-lg w-1/2 animate-pulse"></div>
        </div>

        {/* Sources Skeleton */}
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-3 h-3 bg-perplexity-border rounded-full animate-pulse"></div>
            <div className="h-3 bg-perplexity-border rounded w-16 animate-pulse"></div>
          </div>
          <div className="flex gap-3 overflow-hidden">
            {[1, 2, 3].map((j) => (
              <div key={j} className="w-40 h-[110px] bg-perplexity-panel border border-perplexity-border rounded-xl shrink-0 animate-pulse"></div>
            ))}
          </div>
        </div>

        {/* Answer Skeleton */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-5 h-5 bg-perplexity-border rounded-full animate-pulse"></div>
            <div className="h-4 bg-perplexity-border rounded w-20 animate-pulse"></div>
          </div>
          <div className="space-y-3">
            <div className="h-4 bg-perplexity-border rounded w-full animate-pulse"></div>
            <div className="h-4 bg-perplexity-border rounded w-full animate-pulse"></div>
            <div className="h-4 bg-perplexity-border rounded w-5/6 animate-pulse"></div>
            <div className="h-4 bg-perplexity-border rounded w-full animate-pulse"></div>
            <div className="h-4 bg-perplexity-border rounded w-4/6 animate-pulse"></div>
          </div>
        </div>
      </div>
    ))}
  </div>
);

function App() {
  // State
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Theme State
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');

  // History State
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);

  // Evidence Overlay State
  const [showEvidence, setShowEvidence] = useState(false);
  const [currentEvidenceSources, setCurrentEvidenceSources] = useState<Source[]>([]);
  const [selectedSourceIndex, setSelectedSourceIndex] = useState(0);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Initialize Theme
  useEffect(() => {
    const savedTheme = localStorage.getItem('theme') as 'dark' | 'light' | null;
    if (savedTheme) {
      setTheme(savedTheme);
      document.documentElement.classList.toggle('dark', savedTheme === 'dark');
    } else {
      // Default to dark
      setTheme('dark');
      document.documentElement.classList.add('dark');
    }
  }, []);

  const toggleTheme = () => {
    const newTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
    localStorage.setItem('theme', newTheme);
    document.documentElement.classList.toggle('dark', newTheme === 'dark');
  };

  // Load history from localStorage
  useEffect(() => {
    const savedSessions = localStorage.getItem('gemini_perplexity_history');
    if (savedSessions) {
      try {
        setSessions(JSON.parse(savedSessions));
      } catch (e) {
        console.error("Failed to parse history", e);
      }
    }
  }, []);

  // Save history to localStorage
  useEffect(() => {
    if (sessions.length > 0) {
      localStorage.setItem('gemini_perplexity_history', JSON.stringify(sessions));
    }
  }, [sessions]);

  // Sync current messages to session history
  useEffect(() => {
    if (messages.length > 0) {
      if (!currentSessionId) {
        // Create new session if none exists but we have messages (user just started typing)
        const newId = Date.now().toString();
        const newSession: ChatSession = {
          id: newId,
          title: messages[0].content, // Use first message as title
          messages: messages
        };
        setCurrentSessionId(newId);
        setSessions(prev => [newSession, ...prev]);
      } else {
        // Update existing session
        setSessions(prev => prev.map(s =>
          s.id === currentSessionId
            ? { ...s, messages: messages }
            : s
        ));
      }
    }
  }, [messages, currentSessionId]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [query]);

  const handleSearch = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!query.trim() || isLoading) return;

    const currentQuery = query;
    setQuery('');
    setError(null);
    setIsLoading(true);

    // Add user message
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: currentQuery,
      timestamp: Date.now()
    };

    // Optimistically update messages
    setMessages(prev => [...prev, userMsg]);

    try {
      // Prepare history for API
      const history = messages.map(m => ({
        role: m.role,
        parts: [{ text: m.content }]
      }));

      const response = await generateAnswer(currentQuery, history);

      const aiMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'model',
        content: response.text,
        sources: response.sources,
        timestamp: Date.now()
      };

      setMessages(prev => [...prev, aiMsg]);
    } catch (err) {
      setError("Failed to generate response. Please check your connection or API key.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  };

  const startNewThread = () => {
    setMessages([]);
    setCurrentSessionId(null);
    setQuery('');
    // Optionally focus input
  };

  // Scroll to bottom
  useEffect(() => {
    if (messages.length > 0 && !isLoading && !isHistoryLoading) {
      // Only auto-scroll if it's not the initial load of a long history to avoid jumping
      // But here we want smooth scroll for new messages
      // Using a small timeout to ensure render is complete
      setTimeout(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
      }, 100);
    }
  }, [messages, isLoading, isHistoryLoading]);

  const openEvidence = (sources: Source[], initialIndex: number = 0) => {
    setCurrentEvidenceSources(sources);
    setSelectedSourceIndex(initialIndex);
    setShowEvidence(true);
  };

  // Helper to process text and replace [n] with clickable badges
  const renderMessageContent = (msg: Message) => {

    const processText = (text: string) => {
      const parts = text.split(/(\[\d+\])/g);
      return parts.map((part, index) => {
        const match = part.match(/\[(\d+)\]/);
        if (match) {
          const sourceNum = parseInt(match[1]);
          const sourceIndex = sourceNum - 1;
          // Only render interactive citation if source exists
          if (msg.sources && msg.sources[sourceIndex]) {
            return (
              <span
                key={index}
                onClick={(e) => {
                  e.stopPropagation();
                  openEvidence(msg.sources!, sourceIndex);
                }}
                className="inline-flex items-center justify-center min-w-[16px] h-4 px-0.5 ml-0.5 -mt-2 text-[9px] font-bold text-perplexity-accent bg-perplexity-accent/10 rounded-full cursor-pointer hover:bg-perplexity-accent hover:text-white transition-all align-text-top select-none border border-perplexity-accent/20"
                title={msg.sources[sourceIndex].title}
              >
                {sourceNum}
              </span>
            );
          }
        }
        return part;
      });
    };

    return (
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ node, inline, className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || '')
            return !inline && match ? (
              <div className="rounded-lg overflow-hidden my-6 border border-perplexity-border bg-perplexity-panel shadow-lg">
                <div className="px-4 py-2 bg-perplexity-sidebar border-b border-perplexity-border text-xs text-perplexity-muted flex justify-between items-center">
                  <span className="font-mono">{match[1]}</span>
                  <span className="text-[10px] uppercase tracking-wider opacity-50">Code</span>
                </div>
                <div className="p-4 overflow-x-auto">
                  <code className={`${className} text-sm`} {...props}>
                    {children}
                  </code>
                </div>
              </div>
            ) : (
              <code className={`${className} bg-perplexity-panel px-1.5 py-0.5 rounded text-sm font-mono text-perplexity-text border border-perplexity-border`} {...props}>
                {children}
              </code>
            )
          },
          p: ({ children }) => (
            <p className="mb-4 last:mb-0 leading-7 text-perplexity-text">
              {React.Children.map(children, child =>
                typeof child === 'string' ? processText(child) : child
              )}
            </p>
          ),
          li: ({ children }) => (
            <li className="mb-2 leading-7 text-perplexity-text">
              {React.Children.map(children, child =>
                typeof child === 'string' ? processText(child) : child
              )}
            </li>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-perplexity-text">
              {React.Children.map(children, child =>
                typeof child === 'string' ? processText(child) : child
              )}
            </strong>
          )
        }}
      >
        {msg.content}
      </Markdown>
    );
  };

  return (
    <div className="flex h-screen bg-perplexity-dark text-perplexity-text overflow-hidden font-sans transition-colors duration-300">
      {/* Sidebar - Frozen / Static */}
      <aside
        className="fixed inset-y-0 left-0 z-50 flex flex-col bg-perplexity-sidebar border-r border-perplexity-border hidden md:flex w-16"
      >
        <div className="h-20 flex items-center justify-center flex-shrink-0">
          <div className="w-8 h-8 bg-perplexity-accent rounded-md flex items-center justify-center text-white font-bold text-lg shadow-[0_0_10px_rgba(0,170,170,0.4)] shrink-0 cursor-pointer" onClick={startNewThread}>
            G
          </div>
        </div>

        <nav className="flex-1 w-full space-y-4 px-2 overflow-y-auto custom-scrollbar overflow-x-hidden flex flex-col items-center pt-4">
          <button
            onClick={startNewThread}
            className="flex items-center justify-center p-3 rounded-full bg-perplexity-accent/10 text-perplexity-accent hover:bg-perplexity-accent/20 transition-all font-medium border border-transparent hover:border-perplexity-accent/20"
            title="New Thread"
          >
            <PlusIcon className="w-5 h-5 shrink-0" />
          </button>
        </nav>

        {/* Footer Actions */}
        <div className="p-2 border-t border-perplexity-border space-y-1 flex flex-col items-center">
          <button
            onClick={(e) => { e.stopPropagation(); toggleTheme(); }}
            className="flex items-center justify-center p-3 text-perplexity-muted hover:text-perplexity-text hover:bg-perplexity-border/30 rounded-lg transition-all"
            title={theme === 'dark' ? "Switch to Light Mode" : "Switch to Dark Mode"}
          >
            {theme === 'dark' ? (
              <SunIcon className="w-5 h-5 shrink-0" />
            ) : (
              <MoonIcon className="w-5 h-5 shrink-0" />
            )}
          </button>
        </div>
      </aside>

      {/* Main Content - Adjusted margin for fixed sidebar */}
      <main className="flex-1 flex flex-col relative min-w-0 bg-perplexity-dark md:ml-16 transition-all duration-300">
        <div className="flex-1 overflow-y-auto p-4 md:p-8 scroll-smooth">
          <div className="max-w-[720px] mx-auto min-h-full pb-40">

            {isHistoryLoading ? (
              <HistorySkeleton />
            ) : messages.length === 0 ? (
              <div className="flex items-center justify-center h-[80vh] animate-in fade-in duration-700">
                <HeroGraphic />
              </div>
            ) : (
              <div className="space-y-12">
                {messages.map((msg) => (
                  <div key={msg.id} className="animate-in fade-in slide-in-from-bottom-4 duration-500 group">

                    {/* User Message - Rendered as H1/Title */}
                    {msg.role === 'user' ? (
                      <div className="mb-8">
                        <h1 className="text-3xl font-display font-medium text-perplexity-text tracking-tight leading-tight break-words">
                          {msg.content}
                        </h1>
                      </div>
                    ) : (
                      /* AI Message - Rendered as Article Content */
                      <div className="relative">
                        {/* Sources Section - Cleaner Layout */}
                        {msg.sources && msg.sources.length > 0 && (
                          <div className="mb-8">
                            <div className="flex items-center gap-2 mb-3 text-xs font-bold text-perplexity-muted uppercase tracking-widest">
                              <LibraryIcon className="w-3 h-3" />
                              Sources
                            </div>
                            <div className="flex gap-3 overflow-x-auto pb-4 scrollbar-hide -mx-4 px-4 md:mx-0 md:px-0 mask-linear-fade">
                              {msg.sources.map((source, idx) => (
                                <SourceCard
                                  key={idx}
                                  source={source}
                                  index={idx}
                                  onClick={() => openEvidence(msg.sources!, idx)}
                                />
                              ))}
                              {/* View More Card */}
                              {msg.sources.length > 3 && (
                                <div
                                  onClick={() => openEvidence(msg.sources!, 0)}
                                  className="flex flex-col justify-center items-center w-24 p-3 bg-transparent hover:bg-perplexity-border/30 rounded-lg cursor-pointer transition-colors border border-perplexity-border hover:border-perplexity-muted border-dashed shrink-0 text-perplexity-muted hover:text-perplexity-text h-[100px]"
                                >
                                  <div className="text-xs font-medium">View All</div>
                                </div>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Answer Section */}
                        <div className="flex items-center gap-2 mb-4">
                          <SparkleIcon className="w-5 h-5 text-perplexity-accent" />
                          <span className="text-sm font-bold text-perplexity-text">Answer</span>
                        </div>

                        <div className="prose prose-lg max-w-none text-perplexity-text markdown-content prose-p:leading-7 prose-headings:text-perplexity-text prose-a:no-underline hover:prose-a:underline prose-strong:text-perplexity-text">
                          {renderMessageContent(msg)}
                        </div>

                        {/* Footer Actions */}
                        <div className="mt-6 flex items-center gap-4 border-t border-perplexity-border pt-4">
                          {msg.sources && msg.sources.length > 0 && (
                            <button
                              onClick={() => openEvidence(msg.sources!, 0)}
                              className="flex items-center gap-2 text-xs font-medium text-perplexity-muted hover:text-perplexity-accent transition-colors"
                            >
                              <GlobeIcon className="w-3 h-3" />
                              View Evidence
                            </button>
                          )}
                          <CopyButton text={msg.content} />
                        </div>
                      </div>
                    )}
                  </div>
                ))}

                {isLoading && (
                  <div className="animate-in fade-in duration-500">
                    <div className="flex items-center gap-2 mb-3 text-xs font-bold text-perplexity-muted uppercase tracking-widest animate-pulse">
                      <div className="w-2 h-2 bg-perplexity-accent rounded-full"></div>
                      Reasoning
                    </div>
                    <div className="space-y-3 max-w-2xl">
                      <div className="h-2 bg-perplexity-border rounded w-1/3 animate-pulse"></div>
                      <div className="h-2 bg-perplexity-border rounded w-full animate-pulse"></div>
                      <div className="h-2 bg-perplexity-border rounded w-5/6 animate-pulse"></div>
                    </div>
                  </div>
                )}

                {error && (
                  <div className="p-4 rounded-lg bg-red-900/10 text-red-400 border border-red-900/20 text-sm flex items-center gap-3">
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg>
                    {error}
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>
        </div>

        {/* Input Area */}
        <div className="sticky bottom-0 bg-perplexity-dark p-4 border-t border-transparent z-20">
          {/* Gradient fade top of sticky bar */}
          <div className="absolute -top-10 left-0 right-0 h-10 bg-gradient-to-t from-perplexity-dark to-transparent pointer-events-none"></div>

          <div className="max-w-[720px] mx-auto">
            <form onSubmit={handleSearch} className="relative group">

              <textarea
                ref={textareaRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask follow-up..."
                disabled={isLoading}
                rows={1}
                className="w-full bg-perplexity-sidebar text-perplexity-text placeholder-perplexity-muted rounded-[32px] py-4 pl-5 pr-12 focus:outline-none focus:ring-1 focus:ring-perplexity-border border border-perplexity-border shadow-2xl transition-all text-sm md:text-base resize-none overflow-y-auto custom-scrollbar max-h-[200px]"
                style={{ minHeight: '56px' }}
              />

              <button
                type="submit"
                disabled={!query.trim() || isLoading}
                className={`absolute bottom-3 right-3 p-2 rounded-full transition-all duration-200 ${query.trim() && !isLoading
                  ? 'bg-perplexity-accent text-white hover:bg-[#009999] shadow-lg shadow-perplexity-accent/20'
                  : 'bg-transparent text-gray-600 cursor-not-allowed'
                  }`}
              >
                <ArrowRightIcon className="w-5 h-5" />
              </button>
            </form>

          </div>
        </div>
      </main>

      {/* Evidence Modal */}
      <EvidenceOverlay
        isOpen={showEvidence}
        onClose={() => setShowEvidence(false)}
        sources={currentEvidenceSources}
        selectedIndex={selectedSourceIndex}
        onSelectSource={setSelectedSourceIndex}
      />
    </div>
  );
}

export default App;