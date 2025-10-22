import React, { useState, useEffect, useCallback, useRef } from "react"
import Navbar from "./components/Navbar"
import Cards from "./components/Cards"

const API = import.meta.env.VITE_API_BASE || "http://localhost:8000"

function App() {
  const [cardsData, setCardsData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  const sseRef = useRef(null)
  const pollingRef = useRef(null)
  const healthRef = useRef(null)

  const fetchCards = useCallback(async (source = "manual") => {
    try {
      setLoading(prev => (cardsData.length === 0 ? true : prev))

      const response = await fetch(`${API}/people/cards`)
      if (!response.ok) throw new Error("Failed to fetch cards")

      const data = await response.json()
      const transformed = data.map(person => ({
        personId: person.id,
        name: person.name,
        imageUrl: person.image_url,
        articles: (person.articles || []).slice(0, 3).map(a => ({
          title: a.title,
          summary: a.summary,
          link: a.link,
          publishedAt: a.published_at ?? null,
          articleId: a.id,
        })),
      }))

      // simple change detection (good enough for small payloads)
      const changed = JSON.stringify(transformed) !== JSON.stringify(cardsData)

      if (changed) setCardsData(transformed)
      setError(null)

      // Only bump clock for SSE-trigger OR when data actually changed
      if (source === "sse" || changed) {
        setLastUpdated(new Date())
      }
    } catch (err) {
      console.error("Error fetching cards:", err)
      setError(err.message || String(err))
    } finally {
      setLoading(false)
    }
  }, [cardsData, API])


  const startPolling = useCallback(() => {
    if (pollingRef.current) return
    pollingRef.current = setInterval(() => fetchCards("poll"), 60_000)
  }, [fetchCards])

  const stopPolling = useCallback(() => {
    if (!pollingRef.current) return
    clearInterval(pollingRef.current)
    pollingRef.current = null
  }, [])

  const startSSE = useCallback(() => {
    if (sseRef.current) return
    const es = new EventSource(`${API}/events`, { withCredentials: false })
    sseRef.current = es

    es.onopen = () => {
      stopPolling()
    }

    const onNews = () => fetchCards("sse")
    es.addEventListener("news_update", onNews)

    //es.onmessage = () => fetchCards("sse")

    es.onerror = (e) => {
      console.warn("SSE error; enabling polling fallback", e)
      es.close()
      sseRef.current = null
      startPolling()
      
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
  
      // Try to re-establish SSE after backoff
      reconnectTimeoutRef.current = setTimeout(() => {
        reconnectTimeoutRef.current = null;
        startSSE();
      }, 5000);
    }
  }, [fetchCards, startPolling, stopPolling])

  const stopSSE = useCallback(() => {
    if (!sseRef.current) return
    sseRef.current.close()
    sseRef.current = null
  }, [])

 
  useEffect(() => {
    fetchCards("manual")

    startSSE()

    if (!healthRef.current) {
      healthRef.current = setInterval(() => fetchCards("health"), 5 * 60_000)
    }

    return () => {
      stopSSE()
      stopPolling()
      if (healthRef.current) {
        clearInterval(healthRef.current)
        healthRef.current = null
      }
    }
  }, [fetchCards, startSSE, stopSSE, stopPolling])

  if (loading) {
    return (
      <div>
        <Navbar />
        <div className="w-full min-h-screen flex items-center justify-center">
          <p className="text-2xl">Loading cards...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <Navbar />
        <div className="w-full min-h-screen flex items-center justify-center">
          <p className="text-2xl text-red-500">Error: {error}</p>
        </div>
      </div>
    )
  }

  return (
    <div>
      <Navbar />
      {<div className="px-4 py-2 text-sm text-gray-500">
        {lastUpdated ? `Last updated: ${lastUpdated.toLocaleString()}` : null}
      </div>}
      <Cards cards={cardsData} />
    </div>
  )
}

export default App
