import { Source, ConversationHighlight, ConversationTag } from "../types";

const BACKEND_API_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8010';

interface ChatResponse {
    response: string;
}

interface TranscriptData {
    transcript_id: string;
    domain: string;
    intent: string;
    reason_for_call?: string;
    time_of_interaction?: string;
    conversation: Array<{
        speaker: string;
        text: string;
    }>;
}

interface TranscriptResponse {
    transcript: TranscriptData;
}

interface BatchTranscriptResponse {
    transcripts: TranscriptData[];
    found_count: number;
    not_found_ids: string[];
}

// Generate answer from backend chat endpoint
export const generateAnswer = async (
    query: string,
    threadId: string = "default_user"
): Promise<{ text: string; sources: Source[] }> => {
    try {
        const response = await fetch(`${BACKEND_API_URL}/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                query: query,
                thread_id: threadId
            })
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Backend API Error: ${response.status} - ${errorText}`);
        }

        const data: ChatResponse = await response.json();

        // Extract transcript IDs from the response if any are mentioned
        const transcriptIdPattern = /[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/gi;
        const mentionedIds = data.response.match(transcriptIdPattern) || [];

        // Fetch transcripts if IDs are found
        let sources: Source[] = [];
        if (mentionedIds.length > 0) {
            try {
                const transcripts = await getTranscriptsBatch(mentionedIds);
                sources = transcripts.map((t, i) => formatTranscriptAsSource(t, i));
            } catch (e) {
                console.warn("Could not fetch transcripts:", e);
            }
        }

        return {
            text: data.response,
            sources
        };

    } catch (error) {
        console.error("Chat API Error:", error);
        throw error;
    }
};

// Get a single transcript by ID
export const getTranscript = async (transcriptId: string): Promise<TranscriptData> => {
    const response = await fetch(`${BACKEND_API_URL}/transcript`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            transcript_id: transcriptId
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to fetch transcript: ${response.statusText}`);
    }

    const data: TranscriptResponse = await response.json();
    return data.transcript;
};

// Get multiple transcripts by IDs
export const getTranscriptsBatch = async (transcriptIds: string[]): Promise<TranscriptData[]> => {
    // Remove duplicates
    const uniqueIds = [...new Set(transcriptIds)];

    const response = await fetch(`${BACKEND_API_URL}/transcripts/batch`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            transcript_ids: uniqueIds
        })
    });

    if (!response.ok) {
        throw new Error(`Failed to fetch transcripts: ${response.statusText}`);
    }

    const data: BatchTranscriptResponse = await response.json();
    return data.transcripts;
};

// Check backend health
export const checkHealth = async (): Promise<boolean> => {
    try {
        const response = await fetch(`${BACKEND_API_URL}/health`);
        return response.ok;
    } catch {
        return false;
    }
};

// Get schema stats
export const getSchemaStats = async () => {
    const response = await fetch(`${BACKEND_API_URL}/schema/stats`);
    if (!response.ok) {
        throw new Error(`Failed to fetch schema stats: ${response.statusText}`);
    }
    return response.json();
};

// Helper to format transcript data as a Source for the UI
const formatTranscriptAsSource = (transcript: TranscriptData, index: number): Source => {
    // Add demo highlights/tags to the first transcript for visualization
    let highlights: ConversationHighlight[] = [];
    let tags: ConversationTag[] = [];

    if (index === 0 && transcript.conversation.length > 5) {
        highlights = [
            { startLine: 4, endLine: 6, color: 'bg-emerald-500/10 border-l-2 border-emerald-500' }
        ];
        tags = [
            { line: 4, text: 'Key Info', position: 'top', color: 'bg-emerald-600' },
            { line: 2, text: `Intent: ${transcript.intent}`, position: 'start', color: 'bg-blue-600' }
        ];
    }

    return {
        title: `${transcript.domain} Support: ${transcript.intent}`,
        uri: `transcript://${transcript.transcript_id}`,
        snippet: transcript.conversation
            .map((c) => `${c.speaker}: ${c.text}`)
            .join('\n'),
        highlights,
        tags
    };
};