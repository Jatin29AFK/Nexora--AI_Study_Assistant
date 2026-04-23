export function getPerformanceBand(percentage) {
  if (percentage >= 85) return "Excellent";
  if (percentage >= 70) return "Good";
  if (percentage >= 50) return "Fair";
  return "Needs Improvement";
}

export function scoreQuiz(quiz, quizAnswers) {
  const answerMap = quizAnswers || {};
  let score = 0;
  let answeredCount = 0;
  const topicStats = {};
  const results = [];

  for (const question of quiz.questions) {
    const selectedIndex = answerMap[question.question_id];
    const isAnswered =
      selectedIndex !== undefined && selectedIndex !== null;
    const isCorrect = selectedIndex === question.correct_answer_index;

    if (isAnswered) answeredCount += 1;
    if (isCorrect) score += 1;

    if (!topicStats[question.topic]) {
      topicStats[question.topic] = { total: 0, correct: 0 };
    }

    topicStats[question.topic].total += 1;
    if (isCorrect) topicStats[question.topic].correct += 1;

    results.push({
      question_id: question.question_id,
      topic: question.topic,
      selected_index: selectedIndex ?? null,
      correct_answer_index: question.correct_answer_index,
      is_correct: isCorrect,
      explanation: question.explanation || "No explanation provided.",
    });
  }

  const total = quiz.questions.length;
  const unansweredCount = total - answeredCount;
  const percentage = total ? Number(((score / total) * 100).toFixed(2)) : 0;
  const performanceBand = getPerformanceBand(percentage);

  const weakTopics = Object.entries(topicStats)
    .filter(([, value]) => value.correct / value.total < 0.6)
    .map(([topic]) => topic);

  return {
    quiz_id: quiz.quiz_id,
    score,
    total,
    percentage,
    performance_band: performanceBand,
    answered_count: answeredCount,
    unanswered_count: unansweredCount,
    weak_topics: weakTopics,
    results,
  };
}