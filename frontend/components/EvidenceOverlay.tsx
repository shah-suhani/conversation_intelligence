import React, { useEffect } from 'react';
import { Source, ConversationHighlight, ConversationTag } from '../types';
import { XIcon, ExternalLinkIcon, GlobeIcon } from './Icons';

interface EvidenceOverlayProps {
  isOpen: boolean;
  onClose: () => void;
  sources: Source[];
  selectedIndex: number;
  onSelectSource: (index: number) => void;
}

const getDomain = (url: string) => {
  try {
    return new URL(url).hostname.replace('www.', '');
  } catch {
    return 'source';
  }
};

const isConversation = (text: string) => {
  const lines = text.split('\n').filter(line => line.trim().length > 0);
  // Heuristic: If more than 30% of lines contain a colon likely indicating a speaker
  const colonLines = lines.filter(line => line.includes(':'));
  return lines.length > 2 && (colonLines.length / lines.length) > 0.4;
};

const ConversationView = ({ 
  text, 
  highlights = [], 
  tags = [] 
}: { 
  text: string, 
  highlights?: ConversationHighlight[], 
  tags?: ConversationTag[] 
}) => {
  const lines = text.split('\n').filter(line => line.trim());

  return (
    <div className="mt-8 animate-in fade-in slide-in-from-bottom-2 duration-500">
        <div className="bg-perplexity-panel rounded-xl overflow-hidden shadow-2xl border border-perplexity-border font-mono text-sm leading-relaxed">
            
            {/* Fake Editor Header - Clean, no buttons */}
            <div className="bg-perplexity-sidebar px-4 py-2 border-b border-perplexity-border flex items-center justify-between select-none">
                 <div className="text-perplexity-muted text-xs font-sans tracking-wide opacity-75">transcript.log</div>
            </div>

            <div className="overflow-x-auto">
                <div className="min-w-full inline-block py-2">
                    {lines.map((line, i) => {
                        const splitIndex = line.indexOf(':');
                        const hasSpeaker = splitIndex !== -1;
                        const speakerName = hasSpeaker ? line.substring(0, splitIndex).trim() : '';
                        const content = hasSpeaker ? line.substring(splitIndex + 1).trim() : line;
                        
                        // VS Code-ish syntax colors
                        const isAgent = ['agent', 'system', 'bot', 'support'].some(s => speakerName.toLowerCase().includes(s));
                        
                        // Check highlights
                        const activeHighlight = highlights.find(h => i + 1 >= h.startLine && i + 1 <= h.endLine);
                        const highlightClass = activeHighlight ? (activeHighlight.color || 'bg-white/5') : '';

                        // Check tags
                        const lineTags = tags.filter(t => t.line === i + 1);
                        const topTags = lineTags.filter(t => t.position === 'top');
                        const startTags = lineTags.filter(t => t.position === 'start');
                        const endTags = lineTags.filter(t => t.position === 'end');
                        
                        return (
                            <div key={i} className={`flex flex-col ${highlightClass} transition-colors group relative`}>
                                {/* Top Tags */}
                                {topTags.length > 0 && (
                                    <div className="pl-16 pr-4 pt-2 pb-0.5 flex gap-2">
                                        {topTags.map((tag, idx) => (
                                            <span key={idx} className={`text-[10px] font-sans font-bold px-1.5 py-0.5 rounded ${tag.color || 'bg-blue-600'} text-white shadow-sm uppercase tracking-wider`}>
                                                {tag.text}
                                            </span>
                                        ))}
                                    </div>
                                )}

                                <div className="flex w-full hover:bg-perplexity-border/30">
                                    {/* Gutter / Line Numbers */}
                                    <div className="w-12 shrink-0 bg-transparent text-perplexity-muted text-right pr-4 select-none py-1 group-hover:text-perplexity-text transition-colors opacity-50 text-xs flex items-center justify-end">
                                        {i + 1}
                                    </div>
                                    
                                    {/* Code Content */}
                                    <div className="flex-1 px-4 py-1 whitespace-pre-wrap break-words flex flex-wrap items-baseline gap-2">
                                        
                                        {/* Start Tags */}
                                        {startTags.map((tag, idx) => (
                                            <span key={idx} className={`text-[10px] font-sans font-bold px-1.5 rounded-sm ${tag.color || 'bg-blue-600'} text-white inline-block align-middle`}>
                                                {tag.text}
                                            </span>
                                        ))}

                                        <span className="flex-1">
                                            {hasSpeaker && (
                                                <span className={`font-semibold mr-2 select-none ${isAgent ? 'text-[#569CD6]' : 'text-[#C586C0]'}`}>
                                                    {speakerName}:
                                                </span>
                                            )}
                                            <span className="text-[#CE9178]">{content}</span>
                                            
                                            {/* End Tags */}
                                            {endTags.map((tag, idx) => (
                                                <span key={idx} className={`ml-2 text-[10px] font-sans font-bold px-1.5 rounded-sm ${tag.color || 'bg-blue-600'} text-white inline-block align-middle opacity-80`}>
                                                    {tag.text}
                                                </span>
                                            ))}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    </div>
  );
};

export const EvidenceOverlay: React.FC<EvidenceOverlayProps> = ({
  isOpen,
  onClose,
  sources,
  selectedIndex,
  onSelectSource
}) => {
  if (!isOpen) return null;

  const currentSource = sources[selectedIndex];
  const domain = currentSource ? getDomain(currentSource.uri) : '';
  const isConvo = currentSource ? isConversation(currentSource.snippet) : false;

  // Prevent background scrolling when modal is open
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = 'auto';
    };
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-perplexity-dark/95 backdrop-blur-sm animate-in fade-in duration-200">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-perplexity-border bg-perplexity-dark">
        <h2 className="text-lg font-semibold flex items-center gap-3 text-perplexity-text">
          <div className="p-1.5 bg-perplexity-accent/10 rounded-full text-perplexity-accent">
            <GlobeIcon className="w-5 h-5" />
          </div>
          Evidence Explorer
        </h2>
        <button 
          onClick={onClose}
          className="p-2 hover:bg-perplexity-border/50 rounded-full transition-colors text-perplexity-muted hover:text-perplexity-text"
        >
          <XIcon />
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left Panel: Main Evidence Content */}
        <div className="flex-1 overflow-y-auto p-6 lg:p-10 border-r border-perplexity-border bg-perplexity-dark">
          {currentSource ? (
            <div className="max-w-4xl mx-auto animate-in slide-in-from-bottom-4 duration-300">
              
              {/* Source Header Info */}
              <div className="mb-8">
                 <div className="flex items-center gap-3 mb-4">
                  <span className="bg-perplexity-accent/10 text-perplexity-accent border border-perplexity-accent/20 px-2 py-0.5 rounded text-[11px] font-bold uppercase tracking-wider">
                    Source [{selectedIndex + 1}]
                  </span>
                  <div className="h-4 w-px bg-perplexity-border"></div>
                  <a 
                    href={currentSource.uri} 
                    target="_blank" 
                    rel="noreferrer"
                    className="text-perplexity-muted hover:text-perplexity-accent flex items-center gap-1.5 text-xs transition-colors truncate max-w-md"
                  >
                    <img 
                      src={`https://www.google.com/s2/favicons?domain=${currentSource.uri}&sz=16`} 
                      className="w-3.5 h-3.5 opacity-60"
                      alt=""
                    />
                    {currentSource.uri}
                    <ExternalLinkIcon className="w-3 h-3" />
                  </a>
                </div>

                <h1 className="text-4xl md:text-5xl font-serif text-perplexity-text leading-tight mb-2 tracking-tight">
                  {domain}
                </h1>
                <h2 className="text-lg text-perplexity-muted font-light leading-relaxed">
                    {currentSource.title}
                </h2>
              </div>
              
              {/* Content Area */}
              <div className="prose prose-lg max-w-none prose-p:text-perplexity-text prose-headings:text-perplexity-text prose-strong:text-perplexity-text">
                
                {isConvo ? (
                    <>
                        <div className="bg-perplexity-sidebar p-6 rounded-lg border-l-4 border-perplexity-accent shadow-xl mb-8">
                             <h3 className="text-xs font-bold text-perplexity-accent uppercase tracking-widest mb-3 flex items-center gap-2">
                                <span className="w-1.5 h-1.5 rounded-full bg-perplexity-accent"></span>
                                Summary
                             </h3>
                             <p className="text-perplexity-text text-sm leading-relaxed">
                                This source contains a conversation transcript relevant to your query. The dialogue below details the exchange.
                             </p>
                        </div>
                        <ConversationView 
                          text={currentSource.snippet} 
                          highlights={currentSource.highlights}
                          tags={currentSource.tags}
                        />
                    </>
                ) : (
                    /* Default Extracted Snippet View */
                    <div className="bg-perplexity-panel p-6 md:p-8 rounded-xl border-l-[3px] border-perplexity-accent shadow-2xl relative overflow-hidden group">
                        {/* Background decoration */}
                        <div className="absolute top-0 right-0 w-32 h-32 bg-perplexity-accent/5 rounded-full blur-3xl -mr-16 -mt-16 pointer-events-none"></div>

                        <h3 className="text-xs font-bold text-perplexity-muted uppercase tracking-[0.2em] mb-4 flex items-center gap-2">
                            Extracted Snippet
                        </h3>
                        
                        <p className="text-perplexity-text leading-8 text-lg font-serif whitespace-pre-wrap relative z-10 selection:bg-perplexity-accent/30 selection:text-white">
                           {currentSource.snippet}
                        </p>
                    </div>
                )}
                
                <div className="mt-10 pt-6 border-t border-perplexity-border text-perplexity-muted text-xs">
                  <p>
                    * This content is a snippet extracted from the original webpage. 
                    Referenced sections are highlighted based on relevance to your query. 
                    Visit the original URL for the full context.
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-perplexity-muted">
              <p>Select a source to view evidence.</p>
            </div>
          )}
        </div>

        {/* Right Panel: Related Sources */}
        <div className="w-80 lg:w-96 bg-perplexity-sidebar overflow-y-auto border-l border-perplexity-border hidden md:block">
          <div className="p-5 border-b border-perplexity-border sticky top-0 bg-perplexity-sidebar/95 backdrop-blur z-10">
            <h3 className="font-bold text-xs uppercase tracking-widest text-perplexity-muted">
              Related Sources
            </h3>
          </div>
          <div className="p-4 space-y-3">
            {sources.map((source, idx) => (
              <div 
                key={idx}
                onClick={() => onSelectSource(idx)}
                className={`p-4 rounded-xl cursor-pointer transition-all duration-300 border group ${
                  idx === selectedIndex 
                    ? 'bg-perplexity-panel border-perplexity-accent shadow-[0_0_15px_-3px_rgba(0,170,170,0.15)]' 
                    : 'bg-perplexity-panel hover:bg-perplexity-border/50 border-perplexity-border hover:border-perplexity-border'
                }`}
              >
                <div className="flex items-start justify-between mb-3">
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                    idx === selectedIndex ? 'bg-perplexity-accent text-white' : 'bg-perplexity-border text-perplexity-muted'
                  }`}>
                    {idx + 1}
                  </span>
                  <img 
                    src={`https://www.google.com/s2/favicons?domain=${source.uri}&sz=16`} 
                    alt="" 
                    className="w-4 h-4 opacity-40 group-hover:opacity-100 transition-opacity" 
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                  />
                </div>
                <h4 className={`text-sm font-medium mb-2 line-clamp-2 leading-snug ${
                  idx === selectedIndex ? 'text-perplexity-accent' : 'text-perplexity-text group-hover:text-perplexity-accent'
                }`}>
                  {source.title}
                </h4>
                <div className="text-[11px] text-perplexity-muted line-clamp-2 leading-relaxed">
                    {getDomain(source.uri)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};