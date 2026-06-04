const Footer = () => {
  return (
    <footer className="bg-background">
      <div className="container mx-auto px-4 py-8">
        <p className="text-center text-sm text-muted-foreground">
          &copy; {new Date().getFullYear()} MatchPoint. All rights reserved.
        </p>
      </div>
    </footer>
  )
}

export default Footer
