export interface User {
  id: string;
  email: string;
}

export interface Folder {
  id: string;
  name: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  folder_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

export interface Source {
  source_id: string;
  source_type: 'pdf' | 'youtube' | 'web';
  filename?: string;
  title?: string;
  url?: string;
  ingested_at?: string;
  scraped_at?: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export type SourceFilter = 'pdf' | 'youtube' | 'web';
