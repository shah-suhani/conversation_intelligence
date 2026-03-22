export interface ConversationHighlight {
  startLine: number;
  endLine: number;
  color?: string;
}

export interface ConversationTag {
  line: number;
  text: string;
  position: 'top' | 'start' | 'end';
  color?: string;
}

export interface Source {
  title: string;
  uri: string;
  snippet: string;
  highlights?: ConversationHighlight[];
  tags?: ConversationTag[];
}

export interface GroundingMetadata {
  groundingChunks?: Array<{
    web?: {
      uri: string;
      title: string;
    };
  }>;
  groundingSupports?: Array<{
    segment: {
      startIndex: number;
      endIndex: number;
      text: string;
    };
    groundingChunkIndices: number[];
  }>;
  webSearchQueries?: string[];
}

export interface Message {
  id: string;
  role: 'user' | 'model';
  content: string;
  sources?: Source[];
  timestamp: number;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
}