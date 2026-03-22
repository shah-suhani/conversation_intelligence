import React from 'react';
import { Source } from '../types';

interface SourceCardProps {
  source: Source;
  index: number;
  onClick: () => void;
}

export const SourceCard: React.FC<SourceCardProps> = ({ source, index, onClick }) => {
  // Extract domain from URI for display
  const getDomain = (url: string) => {
    try {
      return new URL(url).hostname.replace('www.', '');
    } catch {
      return 'web';
    }
  };

  return (
    <div 
      onClick={onClick}
      className="
        group relative flex flex-col justify-between 
        w-36 sm:w-40 h-[110px] p-3 
        bg-perplexity-panel hover:bg-perplexity-border/30
        rounded-xl cursor-pointer 
        transition-all duration-300 ease-out
        border border-perplexity-border hover:border-perplexity-muted/50 hover:-translate-y-1 hover:shadow-lg hover:shadow-black/5
        shrink-0 overflow-hidden select-none
      "
    >
      {/* Title with improved typography */}
      <div className="relative z-10">
         <div className="text-[11px] sm:text-xs font-medium text-perplexity-text line-clamp-3 leading-snug group-hover:text-perplexity-accent transition-colors duration-300">
          {source.title}
        </div>
      </div>
      
      {/* Metadata Footer */}
      <div className="flex items-center gap-2 mt-2 relative z-10 pt-2 border-t border-perplexity-border/50 group-hover:border-perplexity-muted/50 transition-colors">
        <div className="flex items-center justify-center w-4 h-4 rounded-full bg-perplexity-sidebar shrink-0 overflow-hidden">
            <img 
                src={`https://www.google.com/s2/favicons?domain=${source.uri}&sz=32`} 
                alt="" 
                className="w-3 h-3 opacity-70 group-hover:opacity-100 transition-opacity"
                onError={(e) => { (e.target as HTMLImageElement).style.opacity = '0'; }}
            />
        </div>
        
        <div className="text-[10px] text-perplexity-muted truncate font-medium max-w-[80px]">
          {getDomain(source.uri)}
        </div>
        
        <div className="ml-auto flex items-center justify-center w-4 h-4 text-[9px] text-perplexity-muted font-mono bg-perplexity-sidebar rounded-full group-hover:text-perplexity-accent group-hover:bg-perplexity-accent/10 transition-colors">
            {index + 1}
        </div>
      </div>
      
      {/* Decorative gradient blob on hover */}
      <div className="absolute inset-0 bg-gradient-to-br from-transparent via-transparent to-perplexity-accent/5 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />
    </div>
  );
};