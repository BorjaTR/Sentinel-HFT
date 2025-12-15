import { SignIn } from "@clerk/nextjs"

export default function SignInPage() {
  return (
    <div className="min-h-screen pt-24 flex items-center justify-center">
      <SignIn
        appearance={{
          elements: {
            rootBox: "mx-auto",
            card: "bg-dark-card border border-dark-border shadow-xl",
          }
        }}
      />
    </div>
  )
}
