import { supabase, getAccessToken } from "./supabase";
import { chunkText } from "./chunking";

export async function listDocuments() {
  const { data, error } = await supabase
    .from("documents")
    .select("id, name, source_type, source_url, size_kb, created_at")
    .order("created_at", { ascending: false });

  if (error) throw error;
  return data || [];
}

export async function createDocumentWithChunks({
  name,
  sourceType,
  sourceUrl = null,
  sizeKb = null,
  rawText,
}) {
  const cleanedText = (rawText || "").replace(/\s+/g, " ").trim();

  if (!cleanedText) {
    throw new Error("The source does not contain enough readable text.");
  }

  const { data: insertedDoc, error: docError } = await supabase
    .from("documents")
    .insert({
      name,
      source_type: sourceType,
      source_url: sourceUrl,
      size_kb: sizeKb,
      raw_text: cleanedText,
    })
    .select("id, name, source_type, source_url, size_kb, created_at")
    .single();

  if (docError) throw docError;

  const chunks = chunkText(cleanedText);
  const rows = chunks.map((text, index) => ({
    document_id: insertedDoc.id,
    chunk_index: index,
    text,
  }));

  if (rows.length > 0) {
    const { error: chunkError } = await supabase.from("chunks").insert(rows);
    if (chunkError) {
      await supabase.from("documents").delete().eq("id", insertedDoc.id);
      throw chunkError;
    }
  }

  return insertedDoc;
}

export async function deleteDocumentById(documentId) {
  const { error } = await supabase.from("documents").delete().eq("id", documentId);
  if (error) throw error;
}

export async function resetWorkspace() {
  const { error } = await supabase
    .from("documents")
    .delete()
    .neq("id", "00000000-0000-0000-0000-000000000000");

  if (error) throw error;
}

async function getFunctionHeaders() {
    const token = await getAccessToken();
    console.log("Supabase access token exists:", !!token);  return {
    Authorization: `Bearer ${token}`,
  };
}

export async function extractUrlContent(url) {
  const headers = await getFunctionHeaders();

  const { data, error } = await supabase.functions.invoke("extract-url", {
    body: { url },
    headers,
  });

  if (error) {
    const message =
      error?.context?.error ||
      error?.message ||
      "Failed to send request to the Edge Function.";
    throw new Error(message);
  }

  if (data?.error) {
    throw new Error(data.error);
  }

  return data;
}

export async function askQuestionViaSupabase({
  query,
  answerMode,
  history,
  documentId = null,
}) {
  const headers = await getFunctionHeaders();

  const { data, error } = await supabase.functions.invoke("ask", {
    body: {
      query,
      answer_mode: answerMode || "balanced",
      history: history || [],
      document_id: documentId,
    },
    headers,
  });

  if (error) throw error;
  return data;
}

export async function generateQuizViaSupabase({
  documentId,
  difficulty,
  numQuestions,
}) {
  const headers = await getFunctionHeaders();

  const { data, error } = await supabase.functions.invoke("generate-quiz", {
    body: {
      document_id: documentId,
      difficulty: difficulty || "medium",
      num_questions: Number(numQuestions),
    },
    headers,
  });

  if (error) throw error;
  return data;
}

export function buildSuggestedQuestions(documents) {
  return (documents || [])
    .slice(0, 3)
    .flatMap((doc) => [
      {
        source_name: doc.name,
        question: `Summarize ${doc.name}`,
      },
      {
        source_name: doc.name,
        question: `What are the key points in ${doc.name}?`,
      },
      {
        source_name: doc.name,
        question: `Explain the main concepts in ${doc.name}`,
      },
    ])
    .slice(0, 6);
}