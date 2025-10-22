import React, { useState } from "react"

const Card = ({ card }) => {
  const [isFlipped, setIsFlipped] = useState(false)
  const [imageError, setImageError] = useState(false)
  const [selected, setSelected] = useState(0) // tells which article is active

  const article = (card.articles && card.articles[selected]) || {}

  const handleTitleTap = (idx) => {
    setSelected(idx)
    setIsFlipped(true) // flip to show link & summary for that title
  }

  const handleCardClick = (e) => {
    const tag = e.target.tagName
    if (tag !== "A" && tag !== "BUTTON") setIsFlipped(!isFlipped)
  }

  return (
    <div className="w-full h-[700px] perspective-1000" onClick={handleCardClick}>
      <div
        className={`relative w-full h-full transition-transform duration-500 transform-style-3d cursor-pointer ${
          isFlipped ? "rotate-y-180" : ""
        }`}
        style={{ transformStyle: "preserve-3d" }}
      >
        {/* FRONT: Person + list of titles */}
        <div
          className="absolute w-full h-full shadow-xl flex flex-col p-4 rounded-lg backface-hidden bg-white"
          style={{ backfaceVisibility: "hidden" }}
        >
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-full bg-gray-300 flex items-center justify-center text-sm font-semibold">
              {card.name ? card.name.charAt(0) : "?"}
            </div>
            <h2 className="text-xl font-bold">{card.name}</h2>
          </div>

          {/* Person image for the selected article */}
          {imageError || !card.imageUrl ? (
            <div className="w-full min-h-[220px] bg-gray-100 rounded-lg flex items-center justify-center mb-4">
              <p className="text-gray-500 text-center px-4">Image not available</p>
            </div>
          ) : (
            <img
              className="w-full min-h-[200px] object-cover rounded-lg mb-4"
              src={card.imageUrl}
              alt={article.title || "Article image"}
              onError={() => setImageError(true)}
            />
          )}

          <p className="text-sm text-gray-500 mb-2">Top articles</p>
          <div className="grid gap-2">
            {(card.articles || []).map((a, idx) => (
              <button
                key={a.articleId || idx}
                className={`text-left px-3 py-2 rounded-md border transition-colors ${
                  idx === selected
                    ? "border-blue-500 bg-blue-50 text-blue-700"
                    : "border-gray-200 hover:bg-gray-50"
                }`}
                onClick={(e) => {
                  e.stopPropagation()
                  handleTitleTap(idx)
                }}
              >
                <div className="text-sm font-semibold line-clamp-2">{a.title}</div>
                {a.publishedAt && (
                  <div className="text-xs text-gray-500 mt-1">
                    {new Date(a.publishedAt).toLocaleString()}
                  </div>
                )}
              </button>
            ))}
          </div>

          <div className="mt-auto text-center text-gray-500">
            <p className="text-xs italic">Tap anywhere to flip</p>
          </div>
        </div>

        {/* BACK: Summary + link for the selected title */}
        <div
          className="absolute w-full h-full shadow-xl flex flex-col p-6 rounded-lg backface-hidden bg-blue-200 text-black"
          style={{ backfaceVisibility: "hidden", transform: "rotateY(180deg)" }}
        >
          <h3 className="text-xl font-bold mb-3">{article.title}</h3>
          <p className="text-base leading-relaxed flex-grow">{article.summary}</p>

          {article.link && (
            <a
              href={article.link}
              target="_blank"
              rel="noopener noreferrer"
              className="bg-white text-blue-700 px-4 py-2 rounded-lg text-center font-semibold hover:bg-gray-100 transition-colors mt-4"
              onClick={(e) => e.stopPropagation()}
            >
              Read Full Article
            </a>
          )}

          {card.articles && card.articles.length > 1 && (
            <div className="mt-4 flex flex-wrap gap-2">
              {card.articles.map((a, idx) => (
                <button
                  key={a.articleId || `dot-${idx}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    setSelected(idx)
                  }}
                  className={`text-xs px-2 py-1 rounded ${
                    idx === selected ? "bg-white text-blue-700" : "bg-white/30"
                  }`}
                  title={a.title}
                >
                  {idx + 1}
                </button>
              ))}
            </div>
          )}

          <p className="text-xs italic mt-3 text-center opacity-90">Tap to flip back</p>
        </div>
      </div>

      {/* helpers */}
      <style jsx>{`
        .perspective-1000 { perspective: 1000px; }
        .transform-style-3d { transform-style: preserve-3d; }
        .backface-hidden { backface-visibility: hidden; }
        .rotate-y-180 { transform: rotateY(180deg); }
      `}</style>
    </div>
  )
}

const Cards = ({ cards = [] }) => {
  const getGridClass = () => {
    const count = cards.length
    if (count === 1) return "max-w-[1240px] mx-auto grid grid-cols-1 gap-8"
    if (count === 2) return "max-w-[1240px] mx-auto grid grid-cols-1 md:grid-cols-2 gap-8"
    return "max-w-[1240px] mx-auto grid grid-cols-1 md:grid-cols-3 gap-8"
  }

  return (
    <div className="w-full pt-10 pb-[10rem] px-[120px] md:px-4 bg-white">
      <div className={getGridClass()}>
        {cards.map((card) => (
          <Card key={card.personId || card.name} card={card} />
        ))}
      </div>
    </div>
  )
}

export default Cards
