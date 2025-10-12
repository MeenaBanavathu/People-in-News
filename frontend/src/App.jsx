import React, { useState, useEffect } from "react"
import Navbar from "./components/Navbar"
import Cards from "./components/Cards"

function App() {
  const [cardsData, setCardsData] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    // Fetch data from FastAPI backend
    const fetchCards = async () => {
      try {
        setLoading(true)
        const response = await fetch('http://localhost:8000/people/cards')
        
        if (!response.ok) {
          throw new Error('Failed to fetch cards')
        }
        
        const data = await response.json()
        console.log('Received Data:', data)
        
        // Transform the API data to match our Cards component format
        const transformedData = data.map(person => 
          ({ personId: person.id, 
            name: person.name, 
            articles: (person.articles || []) .slice(0, 3) .map(a => 
              ({ imageUrl: a.image_url ?? "", 
                title: a.title, 
                summary: a.summary, 
                link: a.link, 
                publishedAt: a.published_at ?? null, 
                articleId: a.id, 
              })) 
        }));
        console.log('Transformed Data:', transformedData)
        setCardsData(transformedData)
        setError(null)
      } catch (err) {
        console.error('Error fetching cards:', err)
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }

    fetchCards()
  }, [])

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
    <>
      <div>
        <Navbar />
        <Cards cards={cardsData} />
      </div>
    </>
  )
}

export default App