import { SignUp } from "@clerk/nextjs"

export default function SignUpPage() {
  return (
    <div className="min-h-screen pt-24 flex items-center justify-center">
      <SignUp
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
