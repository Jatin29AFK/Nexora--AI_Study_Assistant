import { useEffect, useMemo, useState } from "react";
import { Analytics } from "@vercel/analytics/react";
import { ensureAnonymousSession } from "./lib/supabase";
import { extractTextFromPdf } from "./lib/pdf";
import {
  askQuestionViaSupabase,
  buildSuggestedQuestions,
  createDocumentWithChunks,
  deleteDocumentById,
  extractUrlContent,
  generateQuizViaSupabase,
  listDocuments,
  resetWorkspace,
} from "./lib/supabaseApi";
import { scoreQuiz } from "./lib/quiz";

export default function App() {
  const [files, setFiles] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [urlInput, setUrlInput] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);

  const [loadingWorkspace, setLoadingWorkspace] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [addingUrl, setAddingUrl] = useState(false);
  const [asking, setAsking] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState("");

  const [answerMode, setAnswerMode] = useState("");

  const [quizDifficulty, setQuizDifficulty] = useState("");
  const [quizCount, setQuizCount] = useState(5);
  const [selectedQuizSource, setSelectedQuizSource] = useState("");
  const [quiz, setQuiz] = useState(null);
  const [quizAnswers, setQuizAnswers] = useState({});
  const [quizResult, setQuizResult] = useState(null);
  const [generatingQuiz, setGeneratingQuiz] = useState(false);
  const [submittingQuiz, setSubmittingQuiz] = useState(false);

  useEffect(() => {
    async function bootstrap() {
      try {
        setLoadingWorkspace(true);
        await ensureAnonymousSession();
        const docs = await listDocuments();
        setDocuments(docs);
      } catch (err) {
        setError(err.message || "Failed to initialize Nexora.");
      } finally {
        setLoadingWorkspace(false);
      }
    }

    bootstrap();
  }, []);

  const pdfDocuments = useMemo(
    () => documents.filter((doc) => doc.source_type === "pdf"),
    [documents]
  );

  const urlDocuments = useMemo(
    () => documents.filter((doc) => doc.source_type === "url"),
    [documents]
  );

  const quizSources = documents;
  const suggestedQuestions = useMemo(
    () => buildSuggestedQuestions(documents),
    [documents]
  );

  const status = useMemo(() => {
    const busy = uploading || addingUrl || resetting;
    return {
      indexing: busy,
      documents_count: pdfDocuments.length,
      urls_count: urlDocuments.length,
      index_exists: documents.length > 0,
      last_error: null,
      last_index_result: documents.length
        ? {
            pdf_files_indexed: pdfDocuments.length,
            urls_indexed: urlDocuments.length,
            chunks_created: "Stored in Supabase",
          }
        : null,
    };
  }, [documents, pdfDocuments.length, urlDocuments.length, uploading, addingUrl, resetting]);

  async function refreshDocuments() {
    const docs = await listDocuments();
    setDocuments(docs);
    setSelectedQuizSource((prev) => {
      if (prev && docs.some((doc) => doc.id === prev)) return prev;
      return docs[0]?.id || "";
    });
  }

  function handleFileChange(e) {
    setFiles(Array.from(e.target.files || []));
  }

  async function handleUpload(e) {
    e.preventDefault();

    if (files.length === 0) {
      setError("Please select at least one PDF.");
      return;
    }

    setError("");
    setUploading(true);

    try {
      for (const file of files) {
        const rawText = await extractTextFromPdf(file);

        await createDocumentWithChunks({
          name: file.name,
          sourceType: "pdf",
          sizeKb: Math.round(file.size / 1024),
          rawText,
        });
      }

      setFiles([]);
      await refreshDocuments();
    } catch (err) {
      setError(err.message || "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleAddUrl(e) {
    e.preventDefault();

    if (!urlInput.trim()) {
      setError("Please enter a URL.");
      return;
    }

    setError("");
    setAddingUrl(true);

    try {
      const data = await extractUrlContent(urlInput.trim());

      await createDocumentWithChunks({
        name: data.title || urlInput.trim(),
        sourceType: "url",
        sourceUrl: data.finalUrl || urlInput.trim(),
        rawText: data.text,
      });

      setUrlInput("");
      await refreshDocuments();
    } catch (err) {
      setError(err.message || "Could not add URL.");
    } finally {
      setAddingUrl(false);
    }
  }

  async function handleDeleteDocument(documentId, label) {
    const confirmed = window.confirm(`Delete ${label}?`);
    if (!confirmed) return;

    setError("");

    try {
      await deleteDocumentById(documentId);
      await refreshDocuments();
    } catch (err) {
      setError(err.message || "Could not delete source.");
    }
  }

  async function handleResetSession() {
    const confirmed = window.confirm(
      "This will delete all your current Nexora workspace data stored in Supabase for this anonymous session. Continue?"
    );
    if (!confirmed) return;

    setError("");
    setResetting(true);

    try {
      await resetWorkspace();
      setMessages([]);
      setFiles([]);
      setDocuments([]);
      setQuiz(null);
      setQuizAnswers({});
      setQuizResult(null);
      setSelectedQuizSource("");
      setQuestion("");
      setUrlInput("");
    } catch (err) {
      setError(err.message || "Could not reset session.");
    } finally {
      setResetting(false);
    }
  }

  function buildRecentHistory(limit = 6) {
    return messages.slice(-limit).map((msg) => ({
      role: msg.role,
      text: msg.text,
    }));
  }

  function updateAssistantMessage(assistantId, updater) {
  setMessages((prev) =>
    prev.map((msg) => {
      if (msg.id !== assistantId) return msg;
      return typeof updater === "function" ? updater(msg) : { ...msg, ...updater };
    })
  );
}

function splitIntoChunks(text, wordsPerChunk = 12) {
  const words = (text || "").split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];

  const chunks = [];
  for (let i = 0; i < words.length; i += wordsPerChunk) {
    const piece = words.slice(i, i + wordsPerChunk).join(" ");
    chunks.push(piece + (i + wordsPerChunk < words.length ? " " : ""));
  }
  return chunks;
}

async function streamTextLocally(assistantId, fullText, sources = []) {
  const chunks = splitIntoChunks(fullText, 12);

  for (const chunk of chunks) {
    updateAssistantMessage(assistantId, (msg) => ({
      ...msg,
      text: (msg.text || "") + chunk,
    }));

    await new Promise((resolve) => setTimeout(resolve, 45));
  }

  updateAssistantMessage(assistantId, (msg) => ({
    ...msg,
    streaming: false,
    sources,
  }));
}

  async function sendQuestion(questionText) {
  if (!questionText.trim()) {
    setError("Please enter a question.");
    return;
  }

  if (!status.index_exists) {
    setError("Upload PDFs or add URLs first.");
    return;
  }

  setError("");
  const currentQuestion = questionText;
  const recentHistory = buildRecentHistory(6);
  const assistantId = `assistant-${Date.now()}-${Math.random()}`;

  setMessages((prev) => [
    ...prev,
    { role: "user", text: currentQuestion, sources: [] },
    {
      id: assistantId,
      role: "assistant",
      text: "",
      sources: [],
      streaming: true,
    },
  ]);

  setAsking(true);

  try {
    const data = await askQuestionViaSupabase({
      query: currentQuestion,
      answerMode: answerMode || "balanced",
      history: recentHistory,
    });

    const finalText = data.answer || "No answer returned.";
    await streamTextLocally(assistantId, finalText, data.sources || []);
  } catch (err) {
    updateAssistantMessage(assistantId, {
      streaming: false,
      text: "There was an error while getting the answer.",
      sources: [],
    });
    setError(err.message || "Question failed.");
  } finally {
    setAsking(false);
  }
}

  async function handleSuggestedQuestionClick(questionText) {
    setQuestion("");
    await sendQuestion(questionText);
  }

  async function handleAsk(e) {
    e.preventDefault();
    const currentQuestion = question;
    setQuestion("");
    await sendQuestion(currentQuestion);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleAsk(e);
    }
  }

  function clearChat() {
    setMessages([]);
  }

  function resetQuizAttempt() {
    setQuizAnswers({});
    setQuizResult(null);
  }

  function getAnsweredCount() {
    return Object.keys(quizAnswers).length;
  }

  async function handleGenerateQuiz() {
    if (!selectedQuizSource) {
      setError("Please choose a source for quiz generation.");
      return;
    }

    if (!status.index_exists) {
      setError("Upload PDFs or add URLs first.");
      return;
    }

    setError("");
    setGeneratingQuiz(true);
    setQuiz(null);
    setQuizAnswers({});
    setQuizResult(null);

    try {
      const data = await generateQuizViaSupabase({
        documentId: selectedQuizSource,
        difficulty: quizDifficulty || "medium",
        numQuestions: Number(quizCount),
      });

      setQuiz(data);
    } catch (err) {
      setError(err.message || "Quiz generation failed.");
    } finally {
      setGeneratingQuiz(false);
    }
  }

  function handleQuizAnswer(questionId, selectedIndex) {
    setQuizAnswers((prev) => ({
      ...prev,
      [questionId]: selectedIndex,
    }));
  }

  async function handleSubmitQuiz() {
    if (!quiz) {
      setError("Generate a quiz first.");
      return;
    }

    setError("");
    setSubmittingQuiz(true);

    try {
      const result = scoreQuiz(quiz, quizAnswers);
      setQuizResult(result);
    } catch (err) {
      setError(err.message || "Quiz submission failed.");
    } finally {
      setSubmittingQuiz(false);
    }
  }

  if (loadingWorkspace) {
    return (
      <div className="app">
        <div className="bg-orb orb-1" />
        <div className="bg-orb orb-2" />
        <div className="bg-orb orb-3" />
        <main className="shell">
          <section className="chat-card">
            <div className="empty-chat">
              <div className="empty-chat-icon">✦</div>
              <h3>Loading Nexora…</h3>
              <p>Preparing your anonymous Supabase workspace.</p>
            </div>
          </section>
        </main>
        <footer className="app-footer">Created by - JATIN SHUKLA</footer>
        <Analytics />
      </div>
    );
  }

  return (
    <div className="app">
      <div className="bg-orb orb-1" />
      <div className="bg-orb orb-2" />
      <div className="bg-orb orb-3" />

      <header className="hero">
        <div className="hero-copy">
          <span className="eyebrow">Elegant Study Workspace</span>

          <div className="brand-hero">
            <button
              type="button"
              className="brand-reset-button"
              onClick={handleResetSession}
              title="Start new session"
              aria-label="Start new session"
            >
              <img
                src="/nexora-logo.svg"
                alt="Nexora logo"
                className="brand-hero-logo"
              />
            </button>

            <div className="brand-copy">
              <h1 className="brand-hero-title">Nexora</h1>
              <p className="brand-hero-subtitle">
                Upload PDFs and URLs, ask questions, and generate quizzes from your
                study material.
              </p>
            </div>
          </div>
        </div>

        <div className="hero-stats">
          <div className="stat">
            <span className="stat-label">PDFs</span>
            <strong>{status.documents_count}</strong>
          </div>
          <div className="stat">
            <span className="stat-label">URLs</span>
            <strong>{status.urls_count}</strong>
          </div>
          <div className="stat">
            <span className="stat-label">Workspace</span>
            <strong>{status.index_exists ? "Ready" : "Empty"}</strong>
          </div>
          <div className="stat">
            <span className="stat-label">Status</span>
            <strong>{status.indexing ? "Processing" : "Idle"}</strong>
          </div>
        </div>
      </header>

      <main className="shell">
        <aside className="sidebar">
          <section className="card">
            <div className="card-head">
              <div>
                <h2>Upload PDFs</h2>
                <p>Add PDF documents to your Supabase-backed knowledge base.</p>
              </div>
            </div>

            <form onSubmit={handleUpload} className="stack">
              <label className="upload-box">
                <input
                  type="file"
                  accept=".pdf"
                  multiple
                  onChange={handleFileChange}
                />
                <span className="upload-title">Choose PDF files</span>
                <span className="upload-subtitle">
                  PDFs are parsed in browser, then stored as text and chunks
                </span>
              </label>

              <button className="btn btn-primary" type="submit" disabled={uploading}>
                {uploading ? "Uploading..." : "Save Files"}
              </button>
            </form>

            <div className="sub-block">
              <div className="sub-title">Selected Files</div>
              {files.length === 0 ? (
                <div className="empty-mini">No files selected</div>
              ) : (
                <div className="mini-list">
                  {files.map((file) => (
                    <div className="mini-item" key={file.name}>
                      <div>
                        <div className="mini-name">{file.name}</div>
                        <div className="mini-meta">
                          {Math.round(file.size / 1024)} KB
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <h2>Add Website URL</h2>
                <p>Server-side extraction via Supabase Edge Function.</p>
              </div>
            </div>

            <form onSubmit={handleAddUrl} className="stack">
              <input
                className="input"
                type="text"
                placeholder="https://example.com/article"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
              />

              <button className="btn btn-primary" type="submit" disabled={addingUrl}>
                {addingUrl ? "Adding..." : "Add URL"}
              </button>
            </form>
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <h2>Workspace Status</h2>
                <p>Supabase stores your extracted sources and chunks.</p>
              </div>
            </div>

            <div className="stack">
              <div className="status-grid">
                <div className={`status-pill ${status.index_exists ? "ok" : "warn"}`}>
                  {status.index_exists ? "Ready to answer" : "No content yet"}
                </div>
                <div className={`status-pill ${status.indexing ? "info" : "ok"}`}>
                  {status.indexing ? "Processing sources..." : "Idle"}
                </div>
              </div>

              {status.last_index_result && (
                <div className="soft-panel">
                  <div className="soft-row">
                    <span>PDFs indexed</span>
                    <strong>{status.last_index_result.pdf_files_indexed}</strong>
                  </div>
                  <div className="soft-row">
                    <span>URLs indexed</span>
                    <strong>{status.last_index_result.urls_indexed}</strong>
                  </div>
                  <div className="soft-row">
                    <span>Chunks created</span>
                    <strong>{status.last_index_result.chunks_created}</strong>
                  </div>
                </div>
              )}
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <h2>Uploaded PDFs</h2>
                <p>Your current PDF source set.</p>
              </div>
            </div>

            {pdfDocuments.length === 0 ? (
              <div className="empty-mini">No PDFs uploaded yet</div>
            ) : (
              <div className="mini-list">
                {pdfDocuments.map((doc) => (
                  <div className="mini-item row-between" key={doc.id}>
                    <div>
                      <div className="mini-name">{doc.name}</div>
                      <div className="mini-meta">{doc.size_kb || 0} KB</div>
                    </div>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => handleDeleteDocument(doc.id, doc.name)}
                      disabled={uploading || addingUrl || resetting}
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <h2>Saved URLs</h2>
                <p>Your current web sources.</p>
              </div>
            </div>

            {urlDocuments.length === 0 ? (
              <div className="empty-mini">No URLs added yet</div>
            ) : (
              <div className="mini-list">
                {urlDocuments.map((doc) => (
                  <div className="mini-item row-between" key={doc.id}>
                    <div className="url-wrap">
                      <div className="mini-name">{doc.source_url || doc.name}</div>
                    </div>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() =>
                        handleDeleteDocument(doc.id, doc.source_url || doc.name)
                      }
                      disabled={uploading || addingUrl || resetting}
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </aside>

        <section className="chat-card">
          <div className="chat-top">
            <div>
              <h2>Ask Questions</h2>
              <p>Query your Supabase-backed study sources.</p>
            </div>

            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <button className="btn btn-ghost" onClick={handleResetSession}>
                Start New Session
              </button>
              <button
                className="btn btn-ghost"
                onClick={clearChat}
                disabled={messages.length === 0}
              >
                Clear Chat
              </button>
            </div>
          </div>

          <form onSubmit={handleAsk} className="composer">
            <input
              className="composer-input"
              type="text"
              placeholder="Ask something from your uploaded PDFs or URLs..."
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={asking}
            />

            <select
              className="mode-select input"
              value={answerMode}
              onChange={(e) => setAnswerMode(e.target.value)}
              disabled={asking}
              style={{ maxWidth: "180px" }}
            >
              <option value="" disabled>
                Answer Mode
              </option>
              <option value="balanced">Balanced</option>
              <option value="concise">Concise</option>
              <option value="detailed">Detailed</option>
              <option value="bullet">Bullet Summary</option>
              <option value="beginner">Beginner Friendly</option>
              <option value="exam">Exam Style</option>
            </select>

            <button
              className="btn btn-primary composer-btn"
              type="submit"
              disabled={asking || !status.index_exists}
            >
              {asking ? "Thinking..." : "Ask"}
            </button>
          </form>

          {error && <div className="error-box">{error}</div>}

          {!status.indexing && suggestedQuestions.length > 0 && (
            <div className="suggested-section">
              <div className="suggested-header">Suggested questions</div>
              <div className="suggested-chips">
                {suggestedQuestions.map((item, index) => (
                  <button
                    key={`${item.source_name}-${index}`}
                    type="button"
                    className="suggested-chip"
                    onClick={() => handleSuggestedQuestionClick(item.question)}
                    disabled={asking}
                    title={item.source_name}
                  >
                    {item.question}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="chat-feed">
            {messages.length === 0 ? (
              <div className="empty-chat">
                <div className="empty-chat-icon">✦</div>
                <h3>Your workspace is ready</h3>
                <p>
                  Upload PDFs or add URLs, then ask questions or generate a quiz.
                </p>
              </div>
            ) : (
              messages.map((msg, index) => (
                <div
                  key={index}
                  className={`bubble ${
                    msg.role === "user" ? "bubble-user" : "bubble-bot"
                  }`}
                >
                  <div className="bubble-head">
                    <span className="role-badge">
                      {msg.role === "user" ? "You" : "Nexora"}
                    </span>
                  </div>

                  <div className={`bubble-text ${msg.streaming ? "streaming-text" : ""}`}>
  {msg.text || (msg.streaming ? "Thinking..." : "")}
</div>

                  {msg.sources && msg.sources.length > 0 && (
                    <div className="sources">
                      {msg.sources.map((source) => (
                        <span key={source} className="source-chip">
                          {source}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>

          <div className="quiz-section">
            <div className="quiz-header">
              <div>
                <h2>Quiz Studio</h2>
                <p className="muted">
                  Generate a quiz from any uploaded PDF or URL and test yourself.
                </p>
              </div>
            </div>

            <div className="quiz-toolbar">
              <select
                className="quiz-select"
                value={selectedQuizSource}
                onChange={(e) => setSelectedQuizSource(e.target.value)}
                disabled={generatingQuiz}
              >
                <option value="">Select a source</option>
                {quizSources.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.name} ({source.source_type})
                  </option>
                ))}
              </select>

              <input
                className="quiz-count"
                type="number"
                min="3"
                max="10"
                value={quizCount}
                onChange={(e) => setQuizCount(e.target.value)}
                disabled={generatingQuiz}
              />

              <select
                className="quiz-select"
                value={quizDifficulty}
                onChange={(e) => setQuizDifficulty(e.target.value)}
                disabled={generatingQuiz}
                style={{ maxWidth: "150px" }}
              >
                <option value="" disabled>
                  Difficulty
                </option>
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>

              <button
                className="btn btn-secondary"
                type="button"
                onClick={handleGenerateQuiz}
                disabled={generatingQuiz || !selectedQuizSource}
              >
                {generatingQuiz ? "Generating..." : quiz ? "Regenerate Quiz" : "Generate Quiz"}
              </button>

              {quiz && (
                <button
                  className="btn btn-ghost"
                  type="button"
                  onClick={resetQuizAttempt}
                  disabled={submittingQuiz}
                >
                  Retake Quiz
                </button>
              )}
            </div>

            {quiz && (
              <div className="quiz-card">
                <div className="quiz-meta">
                  <h3>{quiz.title}</h3>
                  <p className="muted">Source: {quiz.source_name}</p>
                  <div className="quiz-badges">
                    <span className="source-chip">{quiz.difficulty} difficulty</span>
                    <span className="source-chip">
                      Answered: {getAnsweredCount()} / {quiz.questions.length}
                    </span>
                  </div>
                </div>

                <div className="quiz-questions">
                  {quiz.questions.map((q, index) => (
                    <div key={q.question_id} className="quiz-question-card">
                      <div className="quiz-topic">{q.topic}</div>
                      <div className="quiz-question">
                        <strong>
                          Q{index + 1}. {q.question}
                        </strong>
                      </div>

                      <div className="quiz-options">
                        {q.options.map((option, optIndex) => (
                          <label key={optIndex} className="quiz-option">
                            <input
                              type="radio"
                              name={q.question_id}
                              checked={quizAnswers[q.question_id] === optIndex}
                              onChange={() => handleQuizAnswer(q.question_id, optIndex)}
                            />
                            <span>{option}</span>
                          </label>
                        ))}
                      </div>

                      {quizResult && (
                        <div
                          className={`quiz-feedback ${
                            quizResult.results.find((r) => r.question_id === q.question_id)
                              ?.is_correct
                              ? "quiz-correct"
                              : "quiz-wrong"
                          }`}
                        >
                          <div>
                            <strong>Your answer:</strong>{" "}
                            {(() => {
                              const result = quizResult.results.find(
                                (r) => r.question_id === q.question_id
                              );
                              if (
                                !result ||
                                result.selected_index === null ||
                                result.selected_index === undefined
                              ) {
                                return "Not answered";
                              }
                              return q.options[result.selected_index];
                            })()}
                          </div>

                          <div>
                            <strong>Correct answer:</strong>{" "}
                            {
                              q.options[
                                quizResult.results.find(
                                  (r) => r.question_id === q.question_id
                                )?.correct_answer_index ?? 0
                              ]
                            }
                          </div>

                          <div>
                            <strong>Explanation:</strong> {q.explanation}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                <div className="quiz-actions">
                  <button
                    className="btn btn-primary"
                    type="button"
                    onClick={handleSubmitQuiz}
                    disabled={submittingQuiz}
                  >
                    {submittingQuiz ? "Scoring..." : "Submit Quiz"}
                  </button>
                </div>

                {quizResult && (
                  <div className="quiz-score-box">
                    <h3>
                      Score: {quizResult.score} / {quizResult.total}
                    </h3>
                    <p>Percentage: {quizResult.percentage}%</p>
                    <p>Performance: {quizResult.performance_band}</p>
                    <p>
                      Answered: {quizResult.answered_count} | Unanswered:{" "}
                      {quizResult.unanswered_count}
                    </p>
                  </div>
                )}

                {quizResult?.weak_topics?.length > 0 && (
                  <div className="quiz-weak-topics">
                    <strong>Weak Topics:</strong>
                    <div className="quiz-badges">
                      {quizResult.weak_topics.map((topic) => (
                        <span key={topic} className="source-chip">
                          {topic}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>
      </main>

      <footer className="app-footer">Created by - JATIN SHUKLA</footer>
      <Analytics />
    </div>
  );
}