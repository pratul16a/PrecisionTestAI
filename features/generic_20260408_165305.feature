```gherkin
@automated @generic
Feature: Compliance Reports Navigation
  As a user of the PrecisionTest-GENERIC application
  I want to navigate to compliance reports
  So that I can view and manage compliance information

  @smoke @navigation
  Scenario Outline: Navigate to compliance reports section
    Given I navigate to "<base_url>"
    When I click on "<compliance_section>"
    And I click on "<reports_section>"
    Then I should be able to access the reports page

    Examples:
      | base_url               | compliance_section | reports_section |
      | http://localhost:3000  | Compliance         | Reports         |
```